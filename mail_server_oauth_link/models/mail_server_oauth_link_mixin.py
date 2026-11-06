# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import base64
import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2
import requests
from markupsafe import Markup

from odoo import _, api, fields, models, release
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL, consteq, email_normalize, hmac
from odoo.tools.urls import urljoin

_logger = logging.getLogger(__name__)

# Two kinds of signed values, both shaped
#   <prefix>.<provider>.<kind>.<record id>.<expiration>.<nonce>.<signature>
#
# * the LINK token (olink1) is what the administrator sends to the owner. It is
#   put in the URL fragment, so it never reaches a server log; the owner page
#   moves it into an HttpOnly cookie. It can only open the owner page.
# * the FLOW value (oflow1) is made each time the owner page is shown and goes
#   in the `csrf_token` of the OAuth state (direct mode) or of the IAP callback
#   URL (IAP mode). It can only finish an authorization, never open the page,
#   and lives at most one hour.
#
# Only SHA-256 hashes of the nonces are stored; the signature is an HMAC with
# the database secret over every other part and the mailbox address.
LINK_PREFIX = "olink1"
FLOW_PREFIX = "oflow1"
LINK_SCOPE = "mail_server_oauth_link"
FLOW_SCOPE = "mail_server_oauth_link.flow"
CONTEXT_KEY = "mail_server_oauth_link_flow"
PROVIDERS = ("gmail", "outlook")
MODEL_CODES = {"out": "ir.mail_server", "in": "fetchmail.server"}
DEFAULT_VALIDITY_HOURS = 24
MAX_VALIDITY_HOURS = 24 * 7
FLOW_VALIDITY_SECONDS = 3600
REQUEST_TIMEOUT = 10
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_NUMBER = re.compile(r"[0-9]{1,12}")
_NONCE = re.compile(r"[A-Za-z0-9_-]{32,64}")
_SIGNATURE = re.compile(r"[0-9a-f]{64}")
_KINDS = {
    # kind: (prefix, HMAC scope, field holding the nonce hash)
    "link": (LINK_PREFIX, LINK_SCOPE, "oauth_link_nonce_hash"),
    "flow": (FLOW_PREFIX, FLOW_SCOPE, "oauth_link_flow_hash"),
}


def is_link_token(value):
    """Tell whether a value is meant to be an owner link token (not whether it is valid)."""
    return isinstance(value, str) and value.startswith(LINK_PREFIX + ".")


def is_flow_token(value):
    """Tell whether a value is meant to be an authorization flow value (not whether it is valid)."""
    return isinstance(value, str) and value.startswith(FLOW_PREFIX + ".")


class MailServerOauthLinkMixin(models.AbstractModel):
    _name = "mail.server.oauth.link.mixin"
    _description = "Mail Server OAuth Owner Link"

    # short code of the model inside the tokens, set by the concrete models
    _oauth_link_code = None
    # changing one of these fields cancels the outstanding link
    _oauth_link_watched_fields = ()

    oauth_link_nonce_hash = fields.Char(
        string="Owner Link Nonce Hash",
        groups="base.group_system",
        copy=False,
    )
    oauth_link_flow_hash = fields.Char(
        string="Owner Link Flow Hash",
        groups="base.group_system",
        copy=False,
    )
    oauth_link_expiration = fields.Datetime(
        string="Owner Link Valid Until",
        groups="base.group_system",
        copy=False,
        readonly=True,
    )
    oauth_link_user_id = fields.Many2one(
        "res.users",
        string="Owner Link Created By",
        groups="base.group_system",
        copy=False,
        readonly=True,
        ondelete="set null",
    )

    # ------------------------------------------------------------------
    # Per model hooks
    # ------------------------------------------------------------------

    def _oauth_link_provider(self):
        """Return "gmail", "outlook" or False for the OAuth type of this server."""
        return False

    def _oauth_link_test_connection(self):
        """Log in to the mailbox with the stored tokens; raise if it fails."""
        raise NotImplementedError()

    def _oauth_link_email(self):
        """Normalized address of the mailbox configured on the server."""
        self.ensure_one()
        return email_normalize(self[self._email_field])

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    def write(self, vals):
        watched = [fname for fname in self._oauth_link_watched_fields if fname in vals]
        linked = self.sudo().filtered("oauth_link_nonce_hash") if watched else self.browse()
        before = {record.id: [record[fname] for fname in watched] for record in linked}
        res = super().write(vals)
        changed = linked.filtered(lambda r: [r[fname] for fname in watched] != before[r.id])
        if changed:
            _logger.info("Mail server OAuth link: owner link of %s cancelled by a change of %s", changed, watched)
            changed._oauth_link_revoke()
        return res

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _oauth_link_uses_iap(self, provider):
        """True when the server has no own client id/secret and goes through Odoo IAP."""
        Config = self.env["ir.config_parameter"].sudo()
        prefix = "google_gmail" if provider == "gmail" else "microsoft_outlook"
        return not (
            Config.get_str(f"{prefix}_client_id")
            and Config.get_str(f"{prefix}_client_secret")
        )

    @api.model
    def _oauth_link_validity_hours(self):
        hours = self.env["ir.config_parameter"].sudo().get_int(
            "mail_server_oauth_link.validity_hours"
        ) or DEFAULT_VALIDITY_HOURS
        return min(max(hours, 1), MAX_VALIDITY_HOURS)

    @api.model
    def _oauth_link_hash_nonce(self, nonce):
        return hashlib.sha256(nonce.encode()).hexdigest()

    def _oauth_link_signature(self, kind, provider, expiration, nonce):
        """HMAC (key: database secret) binding a value to this record and its mailbox."""
        self.ensure_one()
        prefix, scope, _field = _KINDS[kind]
        return hmac(
            self.env(su=True),
            scope,
            (
                prefix,
                provider,
                self._name,
                self.id,
                expiration,
                nonce,
                self._oauth_link_email() or "",
            ),
        )

    def _oauth_link_make(self, kind, provider, expiration):
        """Return a new signed value of the given kind and the hash of its nonce."""
        self.ensure_one()
        prefix = _KINDS[kind][0]
        nonce = secrets.token_urlsafe(32)
        signature = self._oauth_link_signature(kind, provider, expiration, nonce)
        value = ".".join((
            prefix, provider, self._oauth_link_code, str(self.id),
            str(expiration), nonce, signature,
        ))
        return value, self._oauth_link_hash_nonce(nonce)

    def _oauth_link_check_can_share(self):
        """Raise when no owner link can be made for this server; return the provider."""
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only an administrator can share the authorization link of a mail server."))
        if not self.active:
            raise UserError(_("The mail server is archived."))
        provider = self._oauth_link_provider()
        if provider not in PROVIDERS:
            raise UserError(_("Choose the Gmail or Outlook OAuth authentication first."))
        if not self._oauth_link_email():
            raise UserError(_("Please enter a valid email address."))
        if self._oauth_link_uses_iap(provider) and release.version_info[-1] != "e":
            if provider == "gmail":
                raise UserError(_("Please configure your Gmail credentials."))
            raise UserError(_("Please configure your Outlook credentials."))
        return provider

    # ------------------------------------------------------------------
    # Link life cycle
    # ------------------------------------------------------------------

    def _oauth_link_generate(self):
        """Create a new owner link token; any older link of this server stops working."""
        provider = self._oauth_link_check_can_share()
        expiration = int(time.time()) + self._oauth_link_validity_hours() * 3600
        token, nonce_hash = self._oauth_link_make("link", provider, expiration)
        self.sudo().write({
            "oauth_link_nonce_hash": nonce_hash,
            "oauth_link_flow_hash": False,
            "oauth_link_expiration": datetime.fromtimestamp(expiration, timezone.utc).replace(tzinfo=None),
            "oauth_link_user_id": self.env.user.id,
        })
        _logger.info(
            "Mail server OAuth link: new owner link for %s #%s, valid until %s",
            self._name, self.id, self.sudo().oauth_link_expiration,
        )
        return token

    def _oauth_link_new_flow(self):
        """Start one authorization attempt of the owner: a value for the OAuth state."""
        self.ensure_one()
        link_expiration = int(self.oauth_link_expiration.replace(tzinfo=timezone.utc).timestamp())
        expiration = min(int(time.time()) + FLOW_VALIDITY_SECONDS, link_expiration)
        flow, flow_hash = self._oauth_link_make("flow", self._oauth_link_provider(), expiration)
        self.sudo().write({"oauth_link_flow_hash": flow_hash})
        return flow

    def _oauth_link_url(self, token):
        """The link to send: the token is in the fragment, which browsers never send to a server."""
        self.ensure_one()
        return urljoin(self.get_base_url(), "/mail_server_oauth_link/authorize") + "#" + token

    def _oauth_link_revoke(self):
        self.sudo().write({
            "oauth_link_nonce_hash": False,
            "oauth_link_flow_hash": False,
            "oauth_link_expiration": False,
            "oauth_link_user_id": False,
        })

    @api.model
    def _oauth_link_reject(self, reason, record=None, level=logging.INFO):
        """Log a refused value. Anonymous junk stays below WARNING (no log flooding)."""
        if record:
            _logger.log(level, "Mail server OAuth link refused for %s #%s: %s", record._name, record.id, reason)
        else:
            _logger.log(level, "Mail server OAuth link refused: %s", reason)
        return None

    @api.model
    def _oauth_link_get_record(self, token, provider=None, kind="link"):
        """Return the server (in sudo) a link token or flow value gives access to, or None.

        Everything is checked before the record is touched: format, provider,
        expiration, the nonce hash stored on the record (single use, revocable),
        the HMAC signature (which also binds the value to the mailbox address),
        then that the server is active and the link creator still an administrator.
        """
        prefix, _scope, hash_field = _KINDS[kind]
        if not isinstance(token, str) or not token.startswith(prefix + "."):
            return self._oauth_link_reject("malformed value")
        parts = token.split(".")
        if len(parts) != 7:
            return self._oauth_link_reject("malformed value")
        _prefix, token_provider, code, rec_id, expiration, nonce, signature = parts
        model_name = MODEL_CODES.get(code)
        if (
            token_provider not in PROVIDERS
            or (provider and token_provider != provider)
            or not model_name
            or model_name not in self.env
            or not _NUMBER.fullmatch(rec_id)
            or not _NUMBER.fullmatch(expiration)
            or not _NONCE.fullmatch(nonce)
            or not _SIGNATURE.fullmatch(signature)
        ):
            return self._oauth_link_reject("malformed value")
        if int(expiration) < time.time():
            return self._oauth_link_reject("expired")
        record = self.env[model_name].sudo().browse(int(rec_id)).exists()
        if not record:
            return self._oauth_link_reject("unknown server")
        stored_hash = record[hash_field]
        if not stored_hash or not consteq(stored_hash, self._oauth_link_hash_nonce(nonce)):
            return self._oauth_link_reject("already used, cancelled or replaced", record)
        expected = record._oauth_link_signature(kind, token_provider, int(expiration), nonce)
        if not consteq(signature, expected):
            return self._oauth_link_reject("wrong signature", record)
        # genuine value from here: refusals are worth a warning
        if not record.active:
            return self._oauth_link_reject("the server is archived", record, logging.WARNING)
        if record._oauth_link_provider() != token_provider:
            return self._oauth_link_reject("the server type changed", record, logging.WARNING)
        creator = record.oauth_link_user_id
        if not creator or not creator.active or not creator.has_group("base.group_system"):
            return self._oauth_link_reject(
                "the administrator who made the link has no Settings rights any more", record, logging.WARNING)
        return record

    def _oauth_link_owns_flow(self, flow, provider):
        self.ensure_one()
        record = self.env["mail.server.oauth.link.mixin"]._oauth_link_get_record(flow, provider, kind="flow")
        return bool(record) and record._name == self._name and record.id == self.id

    def _oauth_link_lock(self):
        """Lock the server row so two callbacks can not use the same link at once."""
        self.ensure_one()
        self.env.cr.execute(SQL(
            "SELECT id FROM %s WHERE id = %s FOR NO KEY UPDATE",
            SQL.identifier(self._table), self.id,
        ))

    # ------------------------------------------------------------------
    # OAuth round trip (owner side)
    # ------------------------------------------------------------------

    def _oauth_link_provider_url(self, flow):
        """URL that starts the sign-in of the owner (Google/Microsoft or Odoo IAP).

        The stock `open_*_uri` methods build it, with the flow value as the CSRF
        token of the state (see the `_get_*_csrf_token` overrides).
        """
        self.ensure_one()
        provider = self._oauth_link_provider()
        record = self.sudo().with_context(**{CONTEXT_KEY: flow})
        if provider == "gmail":
            record.invalidate_recordset(["google_gmail_uri"])
            url = record.open_google_gmail_uri()["url"]
        else:
            record.invalidate_recordset(["microsoft_outlook_uri"])
            url = record.open_microsoft_outlook_uri()["url"]
        if not self._oauth_link_uses_iap(provider):
            # preselect the right account on the sign-in page
            parts = urlsplit(url)
            query = parse_qsl(parts.query, keep_blank_values=True)
            query.append(("login_hint", self[self._email_field]))
            url = urlunsplit(parts._replace(query=urlencode(query)))
        return url

    def _oauth_link_fetch_tokens(self, code=None, iap_refresh_token=None):
        """Exchange the authorization for tokens and find the authorized account.

        :return: (values to write on the server, email of the authorized account)
        """
        self.ensure_one()
        if self._oauth_link_provider() == "gmail":
            if iap_refresh_token:
                # the tokens came through the browser: get a fresh access token
                # from the refresh token so the check below is about that token
                refresh_token = iap_refresh_token
                access_token, expiration = self._fetch_gmail_access_token(refresh_token)
            else:
                refresh_token, access_token, expiration = self._fetch_gmail_refresh_token(code)
            email = self._oauth_link_gmail_email(access_token)
            values = {
                "google_gmail_refresh_token": refresh_token,
                "google_gmail_access_token": access_token,
                "google_gmail_access_token_expiration": expiration,
            }
        else:
            if iap_refresh_token:
                refresh_token = iap_refresh_token
            else:
                refresh_token, _access_token, _expiration = self._fetch_outlook_refresh_token(code)
            # like the stock check: ask a new token server side to get an id
            # token that does not come from the browser
            refresh_token, access_token, id_token, expiration = self._fetch_outlook_access_token(refresh_token)
            email = self._oauth_link_outlook_email(id_token)
            values = {
                "microsoft_outlook_refresh_token": refresh_token,
                "microsoft_outlook_access_token": access_token,
                "microsoft_outlook_access_token_expiration": expiration,
            }
        return values, email

    @api.model
    def _oauth_link_gmail_email(self, access_token):
        """Verified address of the Google account (scope userinfo.email of the stock flow)."""
        response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            raise UserError(_("Google did not tell which account was authorized."))
        data = response.json()
        return data.get("email") if data.get("verified_email") else False

    @api.model
    def _oauth_link_outlook_email(self, id_token):
        """Address in the id token received server side from Microsoft (scope email).

        Microsoft does not promise that `email` is verified. When the optional
        claim `xms_edov` (email domain owner verified) is there and false, the
        address is not used. It is only a first filter: the login to the mailbox
        done before saving (`_oauth_link_test_connection`) is the real proof.
        """
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if "xms_edov" in claims and str(claims["xms_edov"]).lower() not in ("1", "true"):
            return False
        return claims.get("email")

    def _oauth_link_complete(self, values):
        """Store the tokens if they really open the mailbox, consume the link, tell its creator.

        :return: True when saved, False when the mailbox login failed (nothing saved)
        """
        self.ensure_one()
        creator = self.oauth_link_user_id
        try:
            with self.env.cr.savepoint():
                self.write(values)
                self._oauth_link_test_connection()
        except psycopg2.Error:
            raise
        except Exception as e:  # noqa: BLE001 - any failure of the login refuses the tokens
            _logger.warning(
                "Mail server OAuth link: the new tokens of %s #%s do not open the mailbox (%s: %s), nothing saved",
                self._name, self.id, type(e).__name__, e,
            )
            self.invalidate_recordset()
            return False
        self._oauth_link_revoke()
        _logger.info("Mail server OAuth link: the owner connected %s #%s", self._name, self.id)
        self._oauth_link_notify(creator)
        return True

    def _oauth_link_notify(self, user):
        self.ensure_one()
        if not user or not user.active or not user.partner_id:
            return
        record = self.with_context(lang=user.lang)
        body = Markup("<p>%s</p>") % record.env._(
            "The owner of %(email)s authorized the mail server %(server)s.",
            email=self[self._email_field],
            server=self.display_name,
        )
        try:
            with self.env.cr.savepoint():
                self.env["mail.thread"].sudo().message_notify(
                    model=self._name,
                    res_id=self.id,
                    partner_ids=user.partner_id.ids,
                    author_id=self.env.ref("base.partner_root").id,
                    subject=record.env._("Mailbox authorized: %s", self[self._email_field]),
                    body=body,
                )
        except Exception:  # the authorization is saved anyway
            _logger.exception("Mail server OAuth link: could not notify %s", user.login)

    # ------------------------------------------------------------------
    # Admin action
    # ------------------------------------------------------------------

    def action_oauth_link_open(self):
        """Make a new link for the mailbox owner and show it in a dialog.

        The link is only passed in the action context, never stored: the
        database keeps the hash of its nonce only.
        """
        self.ensure_one()
        token = self._oauth_link_generate()
        wizard = self.env["mail.server.oauth.link.wizard"].create({
            "res_model": self._name,
            "res_id": self.id,
            "provider": self._oauth_link_provider(),
            "email": self[self._email_field],
            "expiration": self.sudo().oauth_link_expiration,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Link for the Mailbox Owner"),
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {"mail_server_oauth_link_url": self._oauth_link_url(token)},
        }
