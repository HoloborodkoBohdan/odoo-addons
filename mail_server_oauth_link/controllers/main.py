# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import json
import logging
import time

import requests
from werkzeug.exceptions import BadRequest

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import email_normalize

from odoo.addons.google_gmail.controllers.main import GoogleGmailController
from odoo.addons.microsoft_outlook.controllers.main import MicrosoftOutlookController

from ..models.mail_server_oauth_link_mixin import is_flow_token

_logger = logging.getLogger(__name__)

PROVIDER_NAMES = {"gmail": "Google", "outlook": "Microsoft"}
COOKIE_NAME = "mail_server_oauth_link"
COOKIE_PATH = "/mail_server_oauth_link"
COOKIE_MAX_AGE = 3600
AUTHORIZE_PATH = "/mail_server_oauth_link/authorize"
# arguments of the stock IAP callbacks, all required there
IAP_ARGS = ("model", "rec_id", "csrf_token", "access_token", "refresh_token", "expiration")


def _state_flow(state):
    """Return the owner flow value carried by an OAuth state, if any."""
    try:
        data = json.loads(state)
    except (TypeError, ValueError):
        return None
    flow = data.get("csrf_token") if isinstance(data, dict) else None
    return flow if is_flow_token(flow) else None


def _stock_iap_args(kwargs):
    """The arguments for the stock IAP callback; a clean 400 when one is missing."""
    missing = [name for name in IAP_ARGS if name not in kwargs]
    if missing:
        raise BadRequest("Missing parameters: %s" % ", ".join(missing))
    return {name: kwargs[name] for name in IAP_ARGS}


def _login_redirect():
    """What the stock `auth='user'` callbacks do for a visitor without a session."""
    return request.redirect_query("/web/login", {"redirect": request.httprequest.full_path})


def _secure_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _set_link_cookie(response, token):
    expiration = int(token.split(".")[4])
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=max(0, min(COOKIE_MAX_AGE, expiration - int(time.time()))),
        expires=None,
        path=COOKIE_PATH,
        secure=request.httprequest.scheme == "https",
        httponly=True,
        samesite="Lax",
    )


def _drop_link_cookie(response):
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)


def _render(page_title, message, level="info", status=200, **values):
    response = request.render(
        "mail_server_oauth_link.oauth_link_page",
        {"page_title": page_title, "message": message, "level": level, **values},
        status=status,
    )
    return _secure_headers(response)


def _render_invalid():
    return _render(
        _("Link not valid"),
        _("This authorization link is not valid any more: it was already used, it expired, "
          "or a newer link replaced it. Ask your administrator for a new link."),
        level="warning",
        status=403,
    )


def _confirm(provider, flow, code=None, error=None, iap_refresh_token=None):
    """Finish the owner authorization: check the flow, get the tokens, check the account."""
    Link = request.env["mail.server.oauth.link.mixin"]
    server = Link._oauth_link_get_record(flow, provider, kind="flow")
    if not server:
        return _render_invalid()

    if error or not (code or iap_refresh_token):
        _logger.info("Mail server OAuth link: the owner did not authorize %s #%s (%s)", server._name, server.id, error)
        return _render(
            _("Authorization not given"),
            _("The authorization was cancelled or refused. You can open the link again to retry."),
            level="warning",
        )

    # a concurrent use of the same link waits here, then gets a serialization
    # error and is retried, and the retry finds the link consumed
    server._oauth_link_lock()

    try:
        values, account_email = server._oauth_link_fetch_tokens(code=code, iap_refresh_token=iap_refresh_token)
    except (UserError, requests.exceptions.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
        _logger.warning(
            "Mail server OAuth link: could not get the tokens of %s #%s: %s",
            server._name, server.id, type(e).__name__,
        )
        return _render(
            _("Authorization failed"),
            _("%s did not give the authorization to Odoo. Open the link again to retry, "
              "or contact your administrator.", PROVIDER_NAMES[provider]),
            level="danger",
        )

    mailbox = server[server._email_field]
    if not account_email or email_normalize(account_email) != server._oauth_link_email():
        _logger.warning(
            "Mail server OAuth link: wrong account for %s #%s (%r instead of %r)",
            server._name, server.id, account_email, mailbox,
        )
        return _render(
            _("Wrong account"),
            _("You signed in as %(account)s, but this link is for the mailbox %(mailbox)s. "
              "Nothing was saved. Open the link again and sign in with %(mailbox)s.",
              account=account_email or _("an account without a confirmed address"),
              mailbox=mailbox),
            level="danger",
        )

    if not server._oauth_link_complete(values):
        return _render(
            _("Mailbox not reachable"),
            _("Odoo could not log in to the mailbox %s with this authorization, so nothing was saved. "
              "Check that this account can use the mailbox (IMAP/SMTP access allowed), then open "
              "the link again, or contact your administrator.", mailbox),
            level="danger",
        )

    response = _render(
        _("Mailbox connected"),
        _("Thank you. Odoo can now use the mailbox %s. You can close this page.", mailbox),
        level="success",
    )
    _drop_link_cookie(response)
    return response


class MailServerOauthLinkController(http.Controller):
    @http.route(AUTHORIZE_PATH, type="http", auth="public", methods=["GET"])
    def mail_server_oauth_link_authorize(self, **kwargs):
        """Page of the link sent to the owner.

        With a valid link cookie: says which account to use and starts the
        sign-in. Otherwise: the page that reads the token from the fragment.
        """
        token = request.httprequest.cookies.get(COOKIE_NAME)
        server = token and request.env["mail.server.oauth.link.mixin"]._oauth_link_get_record(token)
        if not server:
            response = _secure_headers(request.render(
                "mail_server_oauth_link.oauth_link_open",
                {"page_title": _("Mailbox authorization")},
            ))
            if token:
                _drop_link_cookie(response)
            return response
        provider = server._oauth_link_provider()
        try:
            url = server._oauth_link_provider_url(server._oauth_link_new_flow())
        except UserError as e:
            return _render(_("Authorization not possible"), str(e), level="danger")
        mailbox = server[server._email_field]
        return _render(
            _("Connect your mailbox to Odoo"),
            _("Your Odoo administrator asks you to let Odoo use the mailbox %(mailbox)s. "
              "Click the button, sign in to %(provider)s with this account and accept the permissions.",
              mailbox=mailbox, provider=PROVIDER_NAMES[provider]),
            details=_("Odoo will check that you signed in with %s and log in to the mailbox "
                      "before it saves anything.", mailbox),
            button_url=url,
            button_label=_("Continue with %s", PROVIDER_NAMES[provider]),
            expiration=server.oauth_link_expiration and server.oauth_link_expiration.strftime("%Y-%m-%d %H:%M"),
        )

    @http.route("/mail_server_oauth_link/open", type="http", auth="public", methods=["POST"])
    def mail_server_oauth_link_open(self, token=None, **kwargs):
        """Receive the token of the fragment once, keep it in an HttpOnly cookie
        and go on with an address that holds no secret."""
        server = request.env["mail.server.oauth.link.mixin"]._oauth_link_get_record(token)
        if not server:
            response = _render_invalid()
            _drop_link_cookie(response)
            return response
        response = _secure_headers(request.redirect(AUTHORIZE_PATH, code=303))
        _set_link_cookie(response, token)
        return response


class GoogleGmailOauthLinkController(GoogleGmailController):
    # auth='public' so the owner does not need an Odoo session; anything that is
    # not an owner flow value still gets the stock behaviour, login included
    @http.route("/google_gmail/confirm", type="http", auth="public")
    def google_gmail_callback(self, code=None, state=None, error=None, **kwargs):
        flow = _state_flow(state)
        if flow:
            return _confirm("gmail", flow, code=code, error=error)
        if request.env.user._is_public():
            return _login_redirect()
        return super().google_gmail_callback(code=code, state=state, error=error, **kwargs)

    @http.route("/google_gmail/iap_confirm", type="http", auth="public")
    def google_gmail_iap_callback(self, **kwargs):
        if is_flow_token(kwargs.get("csrf_token")):
            return _confirm("gmail", kwargs["csrf_token"], iap_refresh_token=kwargs.get("refresh_token"))
        if request.env.user._is_public():
            return _login_redirect()
        return super().google_gmail_iap_callback(**_stock_iap_args(kwargs))


class MicrosoftOutlookOauthLinkController(MicrosoftOutlookController):
    @http.route("/microsoft_outlook/confirm", type="http", auth="public")
    def microsoft_outlook_callback(self, code=None, state=None, error_description=None, **kwargs):
        flow = _state_flow(state)
        if flow:
            return _confirm("outlook", flow, code=code, error=error_description or kwargs.get("error"))
        if request.env.user._is_public():
            return _login_redirect()
        return super().microsoft_outlook_callback(code=code, state=state, error_description=error_description, **kwargs)

    @http.route("/microsoft_outlook/iap_confirm", type="http", auth="public")
    def microsoft_outlook_iap_callback(self, **kwargs):
        if is_flow_token(kwargs.get("csrf_token")):
            return _confirm("outlook", kwargs["csrf_token"], iap_refresh_token=kwargs.get("refresh_token"))
        if request.env.user._is_public():
            return _login_redirect()
        return super().microsoft_outlook_iap_callback(**_stock_iap_args(kwargs))
