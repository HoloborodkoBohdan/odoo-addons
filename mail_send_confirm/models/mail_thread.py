# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import Command, models
from odoo.tools.mail import email_normalize, parse_contact_from_email


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _mail_send_confirm_recipients(
        self, partner_ids=None, partner_cc_ids=None, emails=None, cc_emails=None,
        subtype_id=False, message_type="comment", author_id=None, **notify_kwargs,
    ):
        """Dry run of the notification step of ``message_post``.

        Returns who would receive the message by email if it was posted now
        with these values, filtered by the company setting: only external
        contacts (``partner_share``) or every email recipient. Nothing is
        written: no message, no follower, no partner, no mail.

        :param list partner_ids: explicit recipients (suggested recipients,
          mentions), as given to ``message_post``;
        :param list partner_cc_ids: recipients in copy, as given to ``message_post``;
        :param list emails: recipients without a contact yet, as the chatter
          sends them in ``partner_emails``; ``/mail/message/post`` creates the
          contact when the user may create contacts;
        :param list cc_emails: same for ``partner_cc_emails``;
        :param int subtype_id: message subtype; internal subtypes (notes) never
          ask for a confirmation;
        :param int author_id: author partner, the current user's by default;
        :param notify_kwargs: notification parameters given to ``message_post``
          (``notify_skip_followers``, ``notify_author``, ...);

        :return: list of dicts ``{'id', 'name', 'email'}``, ``id`` being False
          for a contact that does not exist yet;
        """
        self.ensure_one()
        mode = self.env.company.mail_send_confirm_mode
        subtype = self.env["mail.message.subtype"].browse(subtype_id).exists()
        if mode == "never" or not subtype or subtype.internal:
            return []

        partners = self.env["res.partner"].browse(partner_ids or [])
        partners_cc = self.env["res.partner"].browse(partner_cc_ids or [])
        new_contacts = []
        if emails or cc_emails:
            found = self._partner_find_from_emails_single(emails, no_create=True) if emails else partners.browse()
            found_cc = self._partner_find_from_emails_single(cc_emails, no_create=True) if cc_emails else partners.browse()
            partners |= found
            partners_cc |= found_cc
            if self.env.user.has_group("base.group_partner_manager"):
                known = set((found | found_cc).mapped("email_normalized"))
                for email in (emails or []) + (cc_emails or []):
                    name, address = parse_contact_from_email(email)
                    normalized = email_normalize(address)
                    if normalized and normalized not in known:
                        known.add(normalized)
                        new_contacts.append({"id": False, "name": name or normalized, "email": normalized})
        # as in message_post: a partner both in "To" and "Cc" is in "To"
        partners_cc -= partners

        if author_id is None:
            author_id = self._message_compute_author()[0]
        # in-memory message: _notify_get_recipients only reads it
        message = self.env["mail.message"].new({
            "author_id": author_id,
            "incoming_email_cc": False,
            "incoming_email_to": False,
            "message_type": message_type,
            "model": self._name,
            "outgoing_email_to": False,
            "partner_cc_ids": [Command.set(partners_cc.ids)],
            "partner_ids": [Command.set(partners.ids)],
            "res_id": self.id,
            "subtype_id": subtype.id,
        })
        recipients = self._notify_get_recipients(message, **notify_kwargs)
        return [
            {"id": rdata["id"], "name": rdata["name"], "email": rdata["email_normalized"] or ""}
            for rdata in recipients
            if rdata["notif"] == "email" and (mode == "all" or rdata["share"])
        ] + new_contacts
