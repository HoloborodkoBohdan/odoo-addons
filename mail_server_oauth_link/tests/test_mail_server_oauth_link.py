# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import base64
import imaplib
import json
import logging
import re
import time
from contextlib import contextmanager
from html import unescape
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

from odoo import release
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.mail_server_oauth_link.models import mail_server_oauth_link_mixin as link_module

MIXIN_LOGGER = "odoo.addons.mail_server_oauth_link.models.mail_server_oauth_link_mixin"
CONTROLLER_LOGGER = "odoo.addons.mail_server_oauth_link.controllers.main"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GMAIL_IAP = "https://gmail.api.odoo.com/api/mail_oauth/1/"
AUTHORIZE = "/mail_server_oauth_link/authorize"
OPEN = "/mail_server_oauth_link/open"


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status
        self.ok = status < 400
        self.text = json.dumps(data)

    def json(self):
        return self.data

    def raise_for_status(self):
        if not self.ok:
            raise AssertionError("unexpected HTTP error in a test")


def make_id_token(email, **claims):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return ".".join((part({"alg": "none"}), part({"email": email, "name": "Owner ~?>", **claims}), "signature"))


@tagged("post_install", "-at_install")
class TestMailServerOauthLink(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_str("google_gmail_client_id", "gmail-client-id")
        ICP.set_str("google_gmail_client_secret", "gmail-client-secret")
        ICP.set_str("microsoft_outlook_client_id", "outlook-client-id")
        ICP.set_str("microsoft_outlook_client_secret", "outlook-client-secret")
        cls.admin = cls.env.ref("base.user_admin")
        # the notification of the admin stays in Odoo (no email to fake)
        cls.admin.notification_type = "inbox"
        cls.MailServer = cls.env["ir.mail_server"].with_user(cls.admin)
        cls.FetchmailServer = cls.env["fetchmail.server"].with_user(cls.admin)
        cls.gmail_out = cls.MailServer.create({
            "name": "Sales Gmail",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_encryption": "starttls",
            "smtp_authentication": "gmail",
            "smtp_user": "sales@example.com",
            "from_filter": "sales@example.com",
        })
        cls.gmail_out_other = cls.MailServer.create({
            "name": "Other Gmail",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_encryption": "starttls",
            "smtp_authentication": "gmail",
            "smtp_user": "other@example.com",
        })
        cls.outlook_out = cls.MailServer.create({
            "name": "Box Outlook",
            "smtp_host": "smtp.outlook.com",
            "smtp_port": 587,
            "smtp_encryption": "starttls",
            "smtp_authentication": "outlook",
            "smtp_user": "box@example.com",
        })
        cls.gmail_in = cls.FetchmailServer.create({
            "name": "Sales Gmail IMAP",
            "server_type": "gmail",
            "server": "imap.gmail.com",
            "port": 993,
            "is_ssl": True,
            "user": "sales@example.com",
        })
        cls.outlook_in = cls.FetchmailServer.create({
            "name": "Box Outlook IMAP",
            "server_type": "outlook",
            "server": "imap.outlook.com",
            "port": 993,
            "is_ssl": True,
            "user": "box@example.com",
        })

    def setUp(self):
        super().setUp()
        # a visitor without an Odoo user: only the database is known
        self.authenticate(None, None)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @contextmanager
    def mock_providers(self, email, verified=True, token_ok=True, connect="ok", **id_claims):
        """Fake Google, Microsoft, Odoo IAP and the SMTP / IMAP servers.

        :param connect: "ok", "auth" (the mailbox refuses the token) or
            "network" (the mail server can not be reached)
        :yield: list of the HTTP calls; `self.smtp` / `self.imap` get the sessions
        """
        calls = []
        self.smtp, self.imap = [], []

        def fake_post(url, data=None, **kwargs):
            calls.append(("post", url, dict(data or {})))
            if url == GOOGLE_TOKEN_URL:
                if not token_ok:
                    return FakeResponse({"error": "invalid_grant"}, status=400)
                return FakeResponse({
                    "refresh_token": "g-refresh",
                    "access_token": "g-access",
                    "expires_in": 3600,
                })
            if url == MICROSOFT_TOKEN_URL:
                if not token_ok:
                    return FakeResponse({"error_description": "bad code"}, status=400)
                refreshed = data["grant_type"] == "refresh_token"
                return FakeResponse({
                    "refresh_token": "ms-refresh-2" if refreshed else "ms-refresh-1",
                    "access_token": "ms-access-2" if refreshed else "ms-access-1",
                    "expires_in": "3600",
                    "id_token": make_id_token(email, **id_claims),
                })
            raise AssertionError(f"unexpected POST {url}")

        def fake_get(url, params=None, headers=None, **kwargs):
            calls.append(("get", url, dict(params or {}), dict(headers or {})))
            if url == link_module.GOOGLE_USERINFO_URL:
                return FakeResponse({"email": email, "verified_email": verified})
            if url == GMAIL_IAP + "gmail":
                return FakeResponse({"url": "https://iap.example.com/start?x=1"})
            if url == GMAIL_IAP + "gmail_access_token":
                return FakeResponse(["g-access-iap", int(time.time()) + 3600])
            raise AssertionError(f"unexpected GET {url}")

        def fake_smtp(host, port, timeout=None, **kwargs):
            if connect == "network":
                raise OSError("Network is unreachable")
            session = MagicMock(name="smtp")
            session.mail.return_value = (
                (250, b"2.1.0 OK") if connect == "ok"
                else (530, b"5.7.0 Authentication Required")
            )
            session.rcpt.return_value = (250, b"2.1.5 OK")
            self.smtp.append(session)
            return session

        def fake_imap(host, port, timeout=None, **kwargs):
            if connect == "network":
                raise OSError("Network is unreachable")
            session = MagicMock(name="imap")
            if connect == "auth":
                session.authenticate.side_effect = imaplib.IMAP4.error("AUTHENTICATE failed")
            self.imap.append(session)
            return session

        IrMailServer = type(self.env["ir.mail_server"])
        with patch("requests.post", side_effect=fake_post), \
                patch("requests.get", side_effect=fake_get), \
                patch.object(IrMailServer, "_disable_send", return_value=False), \
                patch("smtplib.SMTP", side_effect=fake_smtp), \
                patch("odoo.addons.mail.models.fetchmail.OdooIMAP4_SSL", side_effect=fake_imap):
            yield calls

    def new_token(self, server, user=None):
        return server.with_user(user or self.admin)._oauth_link_generate()

    def new_flow(self, server, user=None):
        """A link, then the flow value the owner page puts in the OAuth state."""
        self.new_token(server, user)
        return server.sudo()._oauth_link_new_flow()

    def gmail_callback(self, flow, code="the-code", **extra):
        state = json.dumps({"model": "ir.mail_server", "id": 0, "csrf_token": flow})
        return self.url_open("/google_gmail/confirm?" + urlencode({"code": code, "state": state, **extra}))

    def outlook_callback(self, flow, code="the-code", **extra):
        state = json.dumps({"model": "fetchmail.server", "id": 0, "csrf_token": flow})
        return self.url_open("/microsoft_outlook/confirm?" + urlencode({"code": code, "state": state, **extra}))

    def get_record(self, token, provider=None, kind="link"):
        return self.env["mail.server.oauth.link.mixin"]._oauth_link_get_record(token, provider, kind=kind)

    def csrf(self):
        page = self.url_open(AUTHORIZE)
        return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    def open_link(self, token):
        """What the browser does with the fragment of the link: post it once."""
        return self.url_open(OPEN, data={"token": token, "csrf_token": self.csrf()}, allow_redirects=False)

    @staticmethod
    def xoauth2(session):
        """Decoded XOAUTH2 string sent on a fake SMTP session."""
        command, argument = session.docmd.call_args[0]
        return base64.b64decode(argument.split(" ", 1)[1]).decode()

    def assert_no_tokens(self, server, prefix):
        server.invalidate_recordset()
        self.assertFalse(server[f"{prefix}_refresh_token"])
        self.assertFalse(server[f"{prefix}_access_token"])

    # ------------------------------------------------------------------
    # link generation
    # ------------------------------------------------------------------

    def test_action_opens_dialog_with_link(self):
        action = self.gmail_out.action_oauth_link_open()
        wizard = self.env[action["res_model"]].browse(action["res_id"])
        self.assertEqual(action["target"], "new")
        self.assertEqual(wizard.email, "sales@example.com")
        self.assertEqual(wizard.provider, "gmail")
        link = wizard.with_context(**action["context"]).link
        url = urlsplit(link)
        self.assertEqual(url.path, AUTHORIZE)
        self.assertFalse(url.query)
        # the token is in the fragment, which browsers never send to a server
        token = url.fragment
        self.assertTrue(token.startswith(f"olink1.gmail.out.{self.gmail_out.id}."))
        self.assertEqual(self.get_record(token), self.gmail_out)
        # only a hash of the secret part is stored, the link itself nowhere
        nonce = token.split(".")[5]
        self.assertTrue(self.gmail_out.oauth_link_nonce_hash)
        self.assertNotIn(nonce, self.gmail_out.oauth_link_nonce_hash)
        self.assertFalse(wizard._fields["link"].store)
        self.assertFalse(wizard.link)
        self.env.flush_all()
        self.env.cr.execute("SELECT * FROM mail_server_oauth_link_wizard WHERE id = %s", [wizard.id])
        self.assertNotIn(nonce, repr(self.env.cr.fetchall()))
        self.assertEqual(self.gmail_out.oauth_link_user_id, self.admin)
        hours = (self.gmail_out.oauth_link_expiration - wizard.create_date).total_seconds() / 3600
        self.assertAlmostEqual(hours, 24, delta=0.1)

    def test_link_kinds(self):
        self.assertTrue(self.new_token(self.outlook_out).startswith(f"olink1.outlook.out.{self.outlook_out.id}."))
        self.assertTrue(self.new_token(self.gmail_in).startswith(f"olink1.gmail.in.{self.gmail_in.id}."))
        self.assertTrue(self.new_token(self.outlook_in).startswith(f"olink1.outlook.in.{self.outlook_in.id}."))
        flow = self.outlook_in.sudo()._oauth_link_new_flow()
        self.assertTrue(flow.startswith(f"oflow1.outlook.in.{self.outlook_in.id}."))

    def test_only_admin_can_get_a_link(self):
        user = new_test_user(self.env, login="ms-user", groups="base.group_user,base.group_erp_manager")
        with self.assertRaises(AccessError):
            self.gmail_out.with_user(user).action_oauth_link_open()
        with self.assertRaises(AccessError):
            self.gmail_out.with_user(user)._oauth_link_generate()

    def test_link_needs_oauth_configuration(self):
        self.gmail_out.smtp_user = "not an email"
        with self.assertRaises(UserError):
            self.gmail_out.action_oauth_link_open()
        server = self.MailServer.create({"name": "Plain", "smtp_host": "smtp.example.com", "smtp_authentication": "login"})
        with self.assertRaises(UserError):
            server.action_oauth_link_open()
        self.outlook_in.action_archive()
        with self.assertRaises(UserError):
            self.outlook_in.action_oauth_link_open()
        # Odoo IAP mode (no own client id) only exists on Enterprise
        self.env["ir.config_parameter"].sudo().set_str("google_gmail_client_secret", "")
        with patch.object(release, "version_info", (20, 0, 0, "final", 0, "")), self.assertRaises(UserError):
            self.gmail_in.action_oauth_link_open()

    def test_validity_parameter(self):
        ICP = self.env["ir.config_parameter"].sudo()
        ICP.set_int("mail_server_oauth_link.validity_hours", 2)
        expiration = int(self.new_token(self.gmail_out).split(".")[4])
        self.assertAlmostEqual(expiration - time.time(), 2 * 3600, delta=60)
        ICP.set_int("mail_server_oauth_link.validity_hours", 1000)
        expiration = int(self.new_token(self.gmail_out).split(".")[4])
        self.assertAlmostEqual(expiration - time.time(), 168 * 3600, delta=60)

    # ------------------------------------------------------------------
    # token checks
    # ------------------------------------------------------------------

    @mute_logger(MIXIN_LOGGER)
    def test_new_link_replaces_previous_one(self):
        first = self.new_token(self.gmail_out)
        flow = self.gmail_out.sudo()._oauth_link_new_flow()
        second = self.new_token(self.gmail_out)
        self.assertFalse(self.get_record(first))
        self.assertFalse(self.get_record(flow, kind="flow"))
        self.assertEqual(self.get_record(second), self.gmail_out)

    @mute_logger(MIXIN_LOGGER)
    def test_tampered_tokens_are_rejected(self):
        token = self.new_token(self.gmail_out)
        self.new_token(self.gmail_out_other)
        parts = token.split(".")

        def variant(index, value):
            changed = list(parts)
            changed[index] = value
            return ".".join(changed)

        signature = parts[6]
        bad_signature = ("0" if signature[0] != "0" else "1") + signature[1:]
        for bad in (
            variant(6, bad_signature),                      # forged signature
            variant(3, str(self.gmail_out_other.id)),       # other record
            variant(2, "in"),                               # other model
            variant(1, "outlook"),                          # other provider
            variant(4, str(int(parts[4]) + 3600)),          # longer validity
            variant(5, parts[5][::-1]),                     # other nonce
            token[:-1],
            token + ".x",
            "olink1." + "x" * 40,
            "",
            None,
        ):
            self.assertFalse(self.get_record(bad), bad)
        self.assertFalse(self.get_record(token, "outlook"))
        self.assertEqual(self.get_record(token, "gmail"), self.gmail_out)

    @mute_logger(MIXIN_LOGGER)
    def test_link_and_flow_are_not_interchangeable(self):
        token = self.new_token(self.gmail_out)
        flow = self.gmail_out.sudo()._oauth_link_new_flow()
        self.assertEqual(self.get_record(token), self.gmail_out)
        self.assertEqual(self.get_record(flow, kind="flow"), self.gmail_out)
        self.assertFalse(self.get_record(flow))
        self.assertFalse(self.get_record(token, kind="flow"))
        # same nonce and signature under the other prefix
        self.assertFalse(self.get_record("oflow1" + token[6:], kind="flow"))
        self.assertFalse(self.get_record("olink1" + flow[6:]))

    @mute_logger(MIXIN_LOGGER)
    def test_expired_values_are_rejected(self):
        token = self.new_token(self.gmail_out)
        flow = self.gmail_out.sudo()._oauth_link_new_flow()
        with patch.object(link_module.time, "time", return_value=time.time() + 3601):
            self.assertFalse(self.get_record(flow, kind="flow"))  # one hour at most
            self.assertEqual(self.get_record(token), self.gmail_out)
        with patch.object(link_module.time, "time", return_value=time.time() + 25 * 3600):
            self.assertFalse(self.get_record(token))
        self.assertEqual(self.get_record(token), self.gmail_out)

    @mute_logger(MIXIN_LOGGER)
    def test_link_cancelled_by_server_changes(self):
        for field, value in (
            ("smtp_user", "boss@example.com"),
            ("smtp_host", "smtp.example.com"),
            ("smtp_authentication", "outlook"),
            ("active", False),
        ):
            server = self.gmail_out.copy({"smtp_user": "sales@example.com"})
            token = self.new_token(server)
            server.name = "Renamed"
            server.smtp_port = 25
            self.assertEqual(self.get_record(token), server, "other fields keep the link")
            server[field] = value
            self.assertFalse(server.oauth_link_nonce_hash, field)
            self.assertFalse(self.get_record(token), field)
            if field == "smtp_user":
                # changing the address back does not bring the old link back
                server.smtp_user = "sales@example.com"
                self.assertFalse(self.get_record(token))
        for field, value in (("user", "boss@example.com"), ("server", "imap.example.com"),
                             ("server_type", "outlook"), ("active", False)):
            server = self.gmail_in.copy()
            token = self.new_token(server)
            server[field] = value
            self.assertFalse(self.get_record(token), field)

    @mute_logger(MIXIN_LOGGER)
    def test_link_of_deleted_server(self):
        server = self.gmail_out.copy({"smtp_user": "sales@example.com"})
        token = self.new_token(server)
        server.unlink()
        self.assertFalse(self.get_record(token))

    @mute_logger(MIXIN_LOGGER)
    def test_creator_must_stay_admin(self):
        other_admin = new_test_user(self.env, login="ms-admin", groups="base.group_user,base.group_system")
        token = self.new_token(self.gmail_out, other_admin)
        self.assertEqual(self.get_record(token), self.gmail_out)
        other_admin.group_ids = [(3, self.env.ref("base.group_system").id)]
        self.assertFalse(other_admin.has_group("base.group_system"))
        self.assertFalse(self.get_record(token))
        token = self.new_token(self.gmail_out)
        self.assertEqual(self.get_record(token), self.gmail_out)
        self.gmail_out.sudo().oauth_link_user_id = other_admin
        self.assertFalse(self.get_record(token))

    @mute_logger(MIXIN_LOGGER)
    def test_archived_server_is_refused(self):
        token = self.new_token(self.gmail_out)
        # archived without going through write (so the link was not cancelled)
        self.env.flush_all()
        self.env.cr.execute("UPDATE ir_mail_server SET active = false WHERE id = %s", [self.gmail_out.id])
        self.env.invalidate_all()
        self.assertFalse(self.get_record(token))

    @mute_logger(MIXIN_LOGGER)
    def test_revoke(self):
        action = self.gmail_out.action_oauth_link_open()
        wizard = self.env[action["res_model"]].browse(action["res_id"]).with_context(**action["context"])
        token = urlsplit(wizard.link).fragment
        wizard.action_revoke()
        self.assertFalse(self.get_record(token))
        self.assertFalse(self.gmail_out.oauth_link_nonce_hash)

    @mute_logger(MIXIN_LOGGER)
    def test_stock_csrf_token_untouched(self):
        stock = self.gmail_out._get_gmail_csrf_token()
        flow = self.new_flow(self.gmail_out)
        other = self.new_flow(self.gmail_out_other)
        token = self.new_token(self.outlook_out)
        server = self.gmail_out.with_context(mail_server_oauth_link_flow=flow)
        self.assertEqual(server._get_gmail_csrf_token(), flow)
        # a value of another server, a link token, or junk never replaces the stock token
        for value in (other, token, "oflow1.junk"):
            server = self.gmail_out.with_context(mail_server_oauth_link_flow=value)
            self.assertEqual(server._get_gmail_csrf_token(), stock)

    def test_log_levels(self):
        token = self.new_token(self.gmail_out)
        forged = token[:-1] + ("0" if token[-1] != "0" else "1")
        with self.assertLogs(MIXIN_LOGGER, level="DEBUG") as logs:
            for junk in ("olink1.gmail.out.1.2.3.4", forged, "olink1." + "x" * 500):
                self.assertFalse(self.get_record(junk))
        self.assertTrue(all(record.levelno < logging.WARNING for record in logs.records))
        # a genuine link refused for another reason is worth a warning
        # (here: made by a user who is not an active administrator)
        self.gmail_out.sudo().oauth_link_user_id = self.env.ref("base.public_user")
        with self.assertLogs(MIXIN_LOGGER, level="WARNING"):
            self.assertFalse(self.get_record(token))

    # ------------------------------------------------------------------
    # owner pages
    # ------------------------------------------------------------------

    def test_provider_url_direct_mode(self):
        flow = self.new_flow(self.gmail_out)
        url = urlsplit(self.gmail_out._oauth_link_provider_url(flow))
        query = parse_qs(url.query)
        self.assertEqual(url.netloc, "accounts.google.com")
        self.assertEqual(json.loads(query["state"][0])["csrf_token"], flow)
        self.assertEqual(query["login_hint"], ["sales@example.com"])
        self.assertTrue(query["redirect_uri"][0].endswith("/google_gmail/confirm"))

        flow = self.new_flow(self.outlook_in)
        url = urlsplit(self.outlook_in._oauth_link_provider_url(flow))
        query = parse_qs(url.query)
        self.assertEqual(url.netloc, "login.microsoftonline.com")
        self.assertEqual(json.loads(query["state"][0])["csrf_token"], flow)
        self.assertEqual(query["login_hint"], ["box@example.com"])
        self.assertTrue(query["redirect_uri"][0].endswith("/microsoft_outlook/confirm"))
        self.assertIn("IMAP.AccessAsUser.All", query["scope"][0])

    def test_owner_opens_the_link(self):
        token = self.new_token(self.gmail_out)
        # 1. the address in the link: a page that posts the fragment
        page = self.url_open(AUTHORIZE)
        self.assertEqual(page.status_code, 200)
        self.assertIn(OPEN, page.text)
        self.assertIn("window.location.hash", page.text)
        # the inline script comes out unescaped
        self.assertIn('document.getElementById("o_oauth_link_form").submit();', page.text)
        self.assertEqual(page.headers.get("Cache-Control"), "no-store")
        # 2. the token goes in an HttpOnly cookie, the next address holds no secret
        response = self.open_link(token)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["Location"].endswith(AUTHORIZE))
        cookie = response.headers["Set-Cookie"]
        self.assertIn(f"mail_server_oauth_link={token}", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/mail_server_oauth_link", cookie)
        self.assertIn("Max-Age=3600", cookie)
        self.assertNotIn("Secure", cookie)  # plain http here; set on https
        # 3. the start page
        page = self.url_open(AUTHORIZE)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Continue with Google", page.text)
        self.assertIn("sales@example.com", page.text)
        self.assertEqual(page.headers.get("Referrer-Policy"), "no-referrer")
        self.assertNotIn(token, page.text)
        href = unescape(re.search(r'href="(https://accounts\.google\.com/[^"]+)"', page.text).group(1))
        flow = json.loads(parse_qs(urlsplit(href).query)["state"][0])["csrf_token"]
        self.assertTrue(flow.startswith("oflow1."))
        self.assertEqual(self.get_record(flow, "gmail", kind="flow"), self.gmail_out)

    @mute_logger(MIXIN_LOGGER)
    def test_owner_opens_an_invalid_link(self):
        response = self.open_link("olink1.gmail.out.1.2.3.4")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Link not valid", response.text)
        self.assertIn("mail_server_oauth_link=;", response.headers["Set-Cookie"])
        # a flow value can not open the page
        flow = self.new_flow(self.gmail_out)
        self.assertEqual(self.open_link(flow).status_code, 403)
        # a stale cookie: back to the page that reads the fragment
        page = self.url_open(AUTHORIZE, cookies={"mail_server_oauth_link": "olink1.junk"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("window.location.hash", page.text)
        self.assertNotIn("Continue with", page.text)

    @mute_logger("odoo.http")
    def test_open_needs_csrf_token(self):
        token = self.new_token(self.gmail_out)
        response = self.url_open(OPEN, data={"token": token}, allow_redirects=False)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("mail_server_oauth_link=", response.headers.get("Set-Cookie", ""))

    # ------------------------------------------------------------------
    # callbacks
    # ------------------------------------------------------------------

    @mute_logger(MIXIN_LOGGER)
    def test_gmail_outgoing_success_as_public_user(self):
        flow = self.new_flow(self.gmail_out)
        with self.mock_providers("Sales@Example.com") as calls:
            response = self.gmail_callback(flow)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mailbox connected", response.text)
        self.assertNotIn("g-refresh", response.text)
        self.assertNotIn("g-access", response.text)
        # the authorization code was exchanged, then the account checked
        self.assertEqual(calls[0][1], GOOGLE_TOKEN_URL)
        self.assertEqual(calls[0][2]["code"], "the-code")
        self.assertEqual(calls[1][1], link_module.GOOGLE_USERINFO_URL)
        self.assertEqual(calls[1][3]["Authorization"], "Bearer g-access")
        # then Odoo logged in to the mailbox with the new token
        [smtp] = self.smtp
        self.assertEqual(self.xoauth2(smtp), "user=sales@example.com\1auth=Bearer g-access\1\1")
        smtp.mail.assert_called_once_with("sales@example.com")

        self.env.invalidate_all()
        self.assertEqual(self.gmail_out.google_gmail_refresh_token, "g-refresh")
        self.assertEqual(self.gmail_out.google_gmail_access_token, "g-access")
        self.assertTrue(self.gmail_out.google_gmail_access_token_expiration)
        self.assertFalse(self.gmail_out.oauth_link_nonce_hash)
        self.assertFalse(self.gmail_out.oauth_link_flow_hash)
        self.assertFalse(self.gmail_out.oauth_link_user_id)
        # nothing else touched
        self.assertFalse(self.gmail_out_other.google_gmail_refresh_token)
        self.assertFalse(self.gmail_in.google_gmail_refresh_token)

        # the admin who made the link is told
        message = self.env["mail.message"].search([
            ("model", "=", "ir.mail_server"), ("res_id", "=", self.gmail_out.id),
        ])
        self.assertEqual(len(message), 1)
        self.assertIn(self.admin.partner_id, message.partner_ids)
        self.assertIn("sales@example.com", message.body)

        # the link works once
        with self.mock_providers("sales@example.com") as calls:
            response = self.gmail_callback(flow, code="another-code")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(calls)

    @mute_logger(MIXIN_LOGGER, CONTROLLER_LOGGER)
    def test_gmail_wrong_account_is_refused(self):
        flow = self.new_flow(self.gmail_out)
        with self.mock_providers("someone@example.com"):
            response = self.gmail_callback(flow)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Wrong account", response.text)
        self.assertIn("someone@example.com", response.text)
        self.assertFalse(self.smtp)
        self.assert_no_tokens(self.gmail_out, "google_gmail")
        # the owner can retry with the right account
        self.assertEqual(self.get_record(flow, kind="flow"), self.gmail_out)

        with self.mock_providers("sales@example.com", verified=False):
            response = self.gmail_callback(flow)
        self.assertIn("Wrong account", response.text)
        self.assert_no_tokens(self.gmail_out, "google_gmail")

    @mute_logger(MIXIN_LOGGER, CONTROLLER_LOGGER)
    def test_gmail_token_error(self):
        flow = self.new_flow(self.gmail_out)
        with self.mock_providers("sales@example.com", token_ok=False):
            response = self.gmail_callback(flow)
        self.assertIn("Authorization failed", response.text)
        self.assert_no_tokens(self.gmail_out, "google_gmail")
        self.assertEqual(self.get_record(flow, kind="flow"), self.gmail_out)

    def test_gmail_cancelled(self):
        flow = self.new_flow(self.gmail_out)
        with self.mock_providers("sales@example.com") as calls:
            response = self.gmail_callback(flow, code="", error="access_denied")
        self.assertIn("Authorization not given", response.text)
        self.assertFalse(calls)
        self.assertEqual(self.get_record(flow, kind="flow"), self.gmail_out)

    @mute_logger(MIXIN_LOGGER)
    def test_tampered_or_wrong_values_are_refused(self):
        token = self.new_token(self.gmail_out)
        flow = self.gmail_out.sudo()._oauth_link_new_flow()
        forged = flow[:-1] + ("0" if flow[-1] != "0" else "1")
        with self.mock_providers("sales@example.com") as calls:
            self.assertEqual(self.gmail_callback(forged).status_code, 403)
            # a Gmail flow can not be used on the Outlook callback
            self.assertEqual(self.outlook_callback(flow).status_code, 403)
            # the link token itself can not finish an authorization: it is
            # not an owner value, so the stock rules apply (login page)
            response = self.url_open(
                "/google_gmail/confirm?" + urlencode({
                    "code": "c", "state": json.dumps({"model": "ir.mail_server", "id": 1, "csrf_token": token}),
                }), allow_redirects=False)
            self.assertIn("/web/login", response.headers["Location"])
        self.assertFalse(calls)

    @mute_logger(MIXIN_LOGGER)
    def test_outlook_incoming_success(self):
        flow = self.new_flow(self.outlook_in)
        with self.mock_providers("BOX@example.com") as calls:
            response = self.outlook_callback(flow)
        self.assertIn("Mailbox connected", response.text)
        self.assertEqual([c[2]["grant_type"] for c in calls], ["authorization_code", "refresh_token"])
        [imap] = self.imap
        mechanism, answer = imap.authenticate.call_args[0]
        self.assertEqual(mechanism, "XOAUTH2")
        self.assertEqual(answer(None), "user=box@example.com\1auth=Bearer ms-access-2\1\1")
        self.env.invalidate_all()
        # the tokens of the server side refresh are stored
        self.assertEqual(self.outlook_in.microsoft_outlook_refresh_token, "ms-refresh-2")
        self.assertEqual(self.outlook_in.microsoft_outlook_access_token, "ms-access-2")
        self.assertFalse(self.outlook_in.oauth_link_nonce_hash)
        self.assertFalse(self.outlook_out.microsoft_outlook_refresh_token)
        # the stock "Test & Confirm" state is left alone
        self.assertEqual(self.outlook_in.state, "draft")

    @mute_logger(MIXIN_LOGGER, CONTROLLER_LOGGER)
    def test_outlook_wrong_or_unverified_account_is_refused(self):
        flow = self.new_flow(self.outlook_out)
        with self.mock_providers("intruder@example.com"):
            response = self.outlook_callback(flow)
        self.assertIn("Wrong account", response.text)
        # an address Microsoft says is not verified by its domain owner
        with self.mock_providers("box@example.com", xms_edov=False):
            response = self.outlook_callback(flow)
        self.assertIn("Wrong account", response.text)
        self.assertFalse(self.smtp)
        self.assert_no_tokens(self.outlook_out, "microsoft_outlook")
        self.assertEqual(self.get_record(flow, kind="flow"), self.outlook_out)
        with self.mock_providers("box@example.com", xms_edov=True):
            response = self.outlook_callback(flow)
        self.assertIn("Mailbox connected", response.text)

    @mute_logger(MIXIN_LOGGER, CONTROLLER_LOGGER, "odoo.addons.mail.models.fetchmail")
    def test_tokens_that_do_not_open_the_mailbox_are_refused(self):
        cases = (
            (self.gmail_out, "sales@example.com", "google_gmail", self.gmail_callback),
            (self.outlook_in, "box@example.com", "microsoft_outlook", self.outlook_callback),
        )
        for server, email, prefix, callback in cases:
            for connect in ("auth", "network"):
                old = {f"{prefix}_refresh_token": "old-refresh", f"{prefix}_access_token": "old-access"}
                server.sudo().write(old)
                flow = self.new_flow(server)
                with self.mock_providers(email, connect=connect):
                    response = callback(flow)
                self.assertIn("Mailbox not reachable", response.text, (server, connect))
                server.invalidate_recordset()
                # the working tokens are kept, the new ones dropped
                self.assertEqual(server[f"{prefix}_refresh_token"], "old-refresh")
                self.assertEqual(server[f"{prefix}_access_token"], "old-access")
                # the owner can fix the mailbox and retry
                self.assertEqual(self.get_record(flow, kind="flow"), server)
        self.assertTrue(self.gmail_out.active)

    @mute_logger(MIXIN_LOGGER)
    def test_gmail_iap_mode(self):
        self.env["ir.config_parameter"].sudo().set_str("google_gmail_client_secret", "")
        with patch.object(release, "version_info", (20, 0, 0, "final", 0, "e")):
            flow = self.new_flow(self.gmail_in)
            with self.mock_providers("sales@example.com") as calls:
                url = self.gmail_in._oauth_link_provider_url(flow)
            self.assertEqual(url, "https://iap.example.com/start?x=1")
            callback = urlsplit(calls[0][2]["callback_url"])
            self.assertEqual(callback.path, "/google_gmail/iap_confirm")
            self.assertEqual(parse_qs(callback.query)["csrf_token"], [flow])

            query = urlencode({
                "model": "fetchmail.server", "rec_id": self.gmail_in.id, "csrf_token": flow,
                "access_token": "from-browser", "refresh_token": "iap-refresh", "expiration": "1",
            })
            with self.mock_providers("sales@example.com") as calls:
                response = self.url_open(f"/google_gmail/iap_confirm?{query}")
        self.assertIn("Mailbox connected", response.text)
        # the access token from the browser is not trusted: a new one is asked
        self.assertEqual(calls[0][1], GMAIL_IAP + "gmail_access_token")
        self.assertEqual(calls[1][3]["Authorization"], "Bearer g-access-iap")
        self.env.invalidate_all()
        self.assertEqual(self.gmail_in.google_gmail_refresh_token, "iap-refresh")
        self.assertEqual(self.gmail_in.google_gmail_access_token, "g-access-iap")

    # ------------------------------------------------------------------
    # stock behaviour kept
    # ------------------------------------------------------------------

    def test_stock_callback_still_needs_a_session(self):
        state = json.dumps({
            "model": "ir.mail_server", "id": self.gmail_out.id,
            "csrf_token": self.gmail_out._get_gmail_csrf_token(),
        })
        with self.mock_providers("sales@example.com") as calls:
            response = self.url_open(
                "/google_gmail/confirm?" + urlencode({"code": "c", "state": state}), allow_redirects=False)
            self.assertIn(response.status_code, (302, 303))
            self.assertIn("/web/login", response.headers["Location"])
            response = self.url_open(
                "/microsoft_outlook/iap_confirm?" + urlencode({
                    "model": "ir.mail_server", "rec_id": self.outlook_out.id, "csrf_token": "x",
                    "access_token": "a", "refresh_token": "r", "expiration": "1",
                }), allow_redirects=False)
            self.assertIn("/web/login", response.headers["Location"])
        self.assertFalse(calls)

    def test_stock_callback_still_works_for_admin(self):
        self.authenticate("admin", "admin")
        state = json.dumps({
            "model": "ir.mail_server", "id": self.gmail_out.id,
            "csrf_token": self.gmail_out._get_gmail_csrf_token(),
        })
        with self.mock_providers("sales@example.com"):
            response = self.url_open(
                "/google_gmail/confirm?" + urlencode({"code": "c", "state": state}), allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertIn(f"/odoo/ir.mail_server/{self.gmail_out.id}", response.headers["Location"])
        self.gmail_out.invalidate_recordset()
        self.assertEqual(self.gmail_out.google_gmail_refresh_token, "g-refresh")

    @mute_logger("odoo.http")
    def test_stock_iap_callback_missing_arguments(self):
        self.authenticate("admin", "admin")
        for path in ("/google_gmail/iap_confirm", "/microsoft_outlook/iap_confirm"):
            response = self.url_open(path + "?model=ir.mail_server", allow_redirects=False)
            self.assertEqual(response.status_code, 400, path)
