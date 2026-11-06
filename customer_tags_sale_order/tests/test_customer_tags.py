# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from lxml import etree

from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestCustomerTags(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vip = cls.env["res.partner.category"].create({"name": "VIP"})
        cls.tagged_partner = cls.env["res.partner"].create(
            {"name": "Tagged customer", "category_id": [(6, 0, cls.vip.ids)]}
        )
        cls.plain_partner = cls.env["res.partner"].create({"name": "Plain customer"})

    def _order(self, partner):
        return self.env["sale.order"].create({"partner_id": partner.id})

    def test_order_follows_partner_tags(self):
        order = self._order(self.tagged_partner)
        self.assertEqual(order.partner_tags, self.vip)
        late = self.env["res.partner.category"].create({"name": "Late payer"})
        self.tagged_partner.category_id = [(4, late.id)]
        self.assertEqual(order.partner_tags, self.vip | late)

    def test_order_without_tags(self):
        self.assertFalse(self._order(self.plain_partner).partner_tags)

    def test_has_tags_filter(self):
        arch = etree.fromstring(self.env["res.partner"].get_view(view_type="search")["arch"])
        node = arch.find(".//filter[@name='partner_has_tags']")
        self.assertIsNotNone(node, "the Has tags filter is missing from the contacts search view")
        partners = self.tagged_partner | self.plain_partner
        found = self.env["res.partner"].search(
            safe_eval(node.get("domain")) + [("id", "in", partners.ids)]
        )
        self.assertEqual(found, self.tagged_partner)

    def test_ukrainian_translation(self):
        self.env["res.lang"]._activate_lang("uk_UA")
        self.env["ir.module.module"]._load_module_terms(
            ["customer_tags_sale_order"], ["uk_UA"], overwrite=True
        )
        field = self.env["ir.model.fields"]._get("sale.order", "partner_tags")
        self.assertEqual(field.with_context(lang="uk_UA").field_description, "Теги клієнта")
