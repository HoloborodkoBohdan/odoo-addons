# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    mail_send_confirm_mode = fields.Selection(
        selection=[
            ("external", "External recipients"),
            ("all", "Any email recipient"),
            ("never", "Never"),
        ],
        string="Confirm Emailed Messages",
        default="external",
        required=True,
        help="When a message sent from the chatter will be emailed to someone, ask the user to "
        "confirm and show who receives it.\n"
        "External recipients: only when a contact without an internal user receives it.\n"
        "Any email recipient: also when only internal users receive it by email.\n"
        "Never: send without asking.",
    )
