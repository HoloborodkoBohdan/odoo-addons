# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models


class CronCategory(models.Model):
    _name = "ir.cron.category"
    _description = "Scheduled Actions Category"
    _order = "name"

    name = fields.Char(
        string="Name",
        required=True,
        index=True,
    )

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        'Category name must be unique!',
    )
