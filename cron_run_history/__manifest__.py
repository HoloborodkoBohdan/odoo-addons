# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Cron Run History",
    "summary": "Record every scheduled action run: status, duration, "
    "records processed and the error traceback",
    "version": "20.0.1.0.0",
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
        "security/ir.access.csv",
        "data/ir_config_parameter_data.xml",
        "views/ir_cron_run_views.xml",
        "views/ir_cron_views.xml",
    ],
    "images": [
        "static/description/banner.png",
    ],
}
