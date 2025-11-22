# Copyright 2025 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Form Group Toggle",
    "summary": "Collapse and expand groups in Odoo form views",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "website": "https://holoborodko.com.ua",
    "author": "Bohdan Holoborodko",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "web",
    ],
    "assets": {
        "web.assets_backend": [
            "form_group_toggle/static/src/xml/form_group_toggle.xml",
            "form_group_toggle/static/src/js/form_group_toggle.js",
            "form_group_toggle/static/src/css/form_group_toggle.scss",
        ],
        "web.qunit_suite_tests": [
            "form_group_toggle/static/tests/form_group_toggle_tests.js",
        ],
    },
    "images": [
        "static/description/banner.png",
    ],
}
