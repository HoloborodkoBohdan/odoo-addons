# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class IrCron(models.Model):
    _inherit = "ir.cron"

    def _get_default_category(self):
        return self.env.ref(
            "cron_category.cron_category_uncategorized", raise_if_not_found=False
        )

    category_id = fields.Many2one(
        comodel_name="ir.cron.category",
        string="Category",
        default=_get_default_category,
        ondelete="set null",
        index=True,
    )
