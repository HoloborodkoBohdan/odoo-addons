# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Chatter Send Confirmation",
    "summary": "Ask for confirmation before a chatter message is emailed to customers",
    "version": "20.0.1.0.0",
    "category": "Productivity/Discuss",
    "website": "https://holoborodko.com.ua",
    "author": "Bohdan Holoborodko",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "mail",
    ],
    "data": [
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mail_send_confirm/static/src/**/*",
        ],
    },
    "images": [
        "static/description/banner.png",
    ],
}
