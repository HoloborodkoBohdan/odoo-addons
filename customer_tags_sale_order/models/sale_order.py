# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    partner_tags = fields.Many2many(
        related="partner_id.category_id",
        string="Customer Tags",
        readonly=True,
    )
