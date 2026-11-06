# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from ..models.mail_server_oauth_link_mixin import MODEL_CODES


class MailServerOauthLinkWizard(models.TransientModel):
    _name = "mail.server.oauth.link.wizard"
    _description = "Link for the Mailbox Owner"

    res_model = fields.Char(string="Server Model", required=True, readonly=True)
    res_id = fields.Many2oneReference(
        string="Server", model_field="res_model", required=True, readonly=True
    )
    provider = fields.Selection(
        [("gmail", "Gmail"), ("outlook", "Outlook")], readonly=True
    )
    email = fields.Char(string="Mailbox", readonly=True)
    # never stored: the link only lives in the action context of the dialog
    link = fields.Char(compute="_compute_link")
    expiration = fields.Datetime(string="Valid Until", readonly=True)

    @api.depends_context("mail_server_oauth_link_url")
    def _compute_link(self):
        self.link = self.env.context.get("mail_server_oauth_link_url") or False

    def _get_server(self):
        self.ensure_one()
        if self.res_model not in MODEL_CODES.values():
            raise AccessError(_("This is not a mail server."))
        return self.env[self.res_model].browse(self.res_id).exists()

    def action_revoke(self):
        """Make the link stop working at once."""
        server = self._get_server()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only an administrator can revoke the authorization link of a mail server."))
        if server:
            server._oauth_link_revoke()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("The link for %s no longer works.", self.email),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
