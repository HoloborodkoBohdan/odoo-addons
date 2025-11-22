# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Cron Category",
    "summary": "Add categories to scheduled actions for better organization",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "website": "https://holoborodko.com.ua",
    "author": "Bohdan Holoborodko",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "base",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron_category_data.xml",
        "views/cron_category_views.xml",
        "views/ir_cron_views.xml",
    ],
    "images": [
        "static/description/banner.png",
    ],
}
