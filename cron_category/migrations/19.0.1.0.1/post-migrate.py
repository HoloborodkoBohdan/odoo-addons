# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import SUPERUSER_ID, api

from odoo.addons.cron_category import _set_uncategorized


def migrate(cr, version):
    # 19.0.1.0.0 left the crons that existed at install time without a category
    _set_uncategorized(api.Environment(cr, SUPERUSER_ID, {}))
