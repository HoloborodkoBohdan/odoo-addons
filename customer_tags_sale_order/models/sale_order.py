from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    partner_tags = fields.Many2many(
        related="partner_id.category_id",
        string="Customer Tags",
        readonly=True
    )
    has_partner_tags = fields.Boolean(
        string="Has Customer Tags",
        compute="_compute_has_partner_tags",
        store=True,
    )

    @api.depends('partner_tags')
    def _compute_has_partner_tags(self):
        for rec in self:
            rec.has_partner_tags = bool(rec.partner_tags)
