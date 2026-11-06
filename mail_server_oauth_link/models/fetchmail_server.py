# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models


class FetchmailServer(models.Model):
    _name = "fetchmail.server"
    _inherit = ["fetchmail.server", "mail.server.oauth.link.mixin"]

    _oauth_link_code = "in"
    _oauth_link_watched_fields = ("active", "server", "server_type", "user")

    def _oauth_link_provider(self):
        self.ensure_one()
        if self.server_type in ("gmail", "outlook"):
            return self.server_type
        return False

    def _oauth_link_test_connection(self):
        """Stock IMAP connection of this server: XOAUTH2 login as `user` and
        selection of the INBOX. Unlike the stock "Test & Confirm" button it does
        not change the server state, so fetching does not start by itself.
        """
        self.ensure_one()
        connection = self._connect__()
        try:
            connection.disconnect()
        except Exception:  # noqa: BLE001 - the login itself succeeded
            pass
