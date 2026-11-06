# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestCronCategory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uncategorized = cls.env.ref("cron_category.cron_category_uncategorized")

    def test_existing_crons_get_uncategorized(self):
        # crons created before the module was installed must not stay without a category
        crons = self.env["ir.cron"].with_context(active_test=False).search([])
        self.assertTrue(crons)
        self.assertFalse(crons.filtered(lambda cron: not cron.category_id))

    def test_new_cron_defaults_to_uncategorized(self):
        cron = self.env["ir.cron"].create({
            "name": "Test cron",
            "model_id": self.env.ref("base.model_res_partner").id,
            "state": "code",
            "code": "pass",
            "interval_number": 1,
            "interval_type": "days",
        })
        self.assertEqual(cron.category_id, self.uncategorized)

    def test_category_name_is_unique(self):
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.env["ir.cron.category"].create({"name": self.uncategorized.name})
            self.env.flush_all()

    def test_search_panel(self):
        arch = self.env["ir.cron"].get_view(view_type="search")["arch"]
        self.assertIn("<searchpanel", arch)
        self.assertIn('name="group_category"', arch)
        reports = self.env["ir.cron.category"].create({"name": "Reports"})  # empty, still listed
        result = self.env["ir.cron"].search_panel_select_range(
            "category_id", enable_counters=True, expand=True
        )
        counts = {value["id"]: value["__count"] for value in result["values"]}
        crons = self.env["ir.cron"].search([])
        self.assertEqual(counts[self.uncategorized.id], len(crons.filtered(lambda c: c.category_id == self.uncategorized)))
        self.assertEqual(counts[reports.id], 0)
