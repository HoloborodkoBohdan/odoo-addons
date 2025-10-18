# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Customer Tags in Sale Order",
    "summary": "Show customer tags in sale order",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "website": "https://holoborodko.com.ua/?ref=customer_tags_sale_order",
    "author": "Bohdan Holoborodko",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "contacts",
        "sale_management",
    ],
    "data": [
        "views/sale_order.xml",
        "views/res_partner.xml",
    ],
    'images': [
        'static/description/baner.png',
        'static/description/partner-sales-tag.png',
    ],
}
