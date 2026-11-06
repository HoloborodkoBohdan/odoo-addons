# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from . import models


def _set_uncategorized(env):
    """Give the Uncategorized category to every cron that has none.

    The field default only applies to crons created after the install: it is
    evaluated when the column is added, before the category record is loaded.
    """
    uncategorized = env.ref("cron_category.cron_category_uncategorized", raise_if_not_found=False)
    if uncategorized:
        crons = env["ir.cron"].with_context(active_test=False).search([("category_id", "=", False)])
        crons.category_id = uncategorized


def post_init_hook(env):
    _set_uncategorized(env)
