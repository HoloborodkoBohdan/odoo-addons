# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mail_send_confirm_mode = fields.Selection(
        related="company_id.mail_send_confirm_mode",
        readonly=False,
    )
