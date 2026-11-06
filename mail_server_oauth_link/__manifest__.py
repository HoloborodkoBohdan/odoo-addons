# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Mail Server OAuth Link",
    "summary": "Send the Gmail / Outlook authorization link of a mail server "
    "to the mailbox owner instead of opening it yourself",
    "version": "20.0.1.0.0",
    "category": "Productivity/Discuss",
    "website": "https://holoborodko.com.ua",
    "author": "Bohdan Holoborodko",
    "license": "AGPL-3",
    "application": False,
    "installable": True,
    "depends": [
        "google_gmail",
        "microsoft_outlook",
    ],
    "data": [
        "security/ir.access.csv",
        "wizard/mail_server_oauth_link_wizard_views.xml",
        "views/ir_mail_server_views.xml",
        "views/fetchmail_server_views.xml",
        "views/templates.xml",
    ],
    "images": [
        "static/description/banner.png",
    ],
}
