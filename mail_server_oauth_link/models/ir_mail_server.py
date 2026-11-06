# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import _, models
from odoo.exceptions import UserError


class IrMailServer(models.Model):
    _name = "ir.mail_server"
    _inherit = ["ir.mail_server", "mail.server.oauth.link.mixin"]

    _oauth_link_code = "out"
    _oauth_link_watched_fields = ("active", "smtp_host", "smtp_authentication", "smtp_user")

    def _oauth_link_provider(self):
        self.ensure_one()
        if self.smtp_authentication in ("gmail", "outlook"):
            return self.smtp_authentication
        return False

    def _oauth_link_test_connection(self):
        """Stock SMTP connection of this server (XOAUTH2 as `smtp_user`), then the
        MAIL FROM and RCPT TO steps of the stock connection test, with the mailbox
        address. Nothing is sent. A token that does not open the mailbox fails here.
        """
        self.ensure_one()
        email = self._oauth_link_email()
        smtp = self._connect__(mail_server_id=self.id, smtp_from=email)
        if smtp is None:
            raise UserError(_("Sending emails is disabled on this database."))
        try:
            code, reply = smtp.mail(email)
            if code != 250:
                raise UserError(_("The server refused the sender address: %s", reply))
            code, reply = smtp.rcpt(email)
            if code not in (250, 251):
                raise UserError(_("The server refused the recipient address: %s", reply))
            smtp.rset()
        finally:
            try:
                smtp.close()
            except Exception:  # noqa: BLE001 - already failing or done
                pass
