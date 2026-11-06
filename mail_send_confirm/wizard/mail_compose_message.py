# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    def mail_send_confirm_get_recipients(self):
        """Who would receive by email what ``action_send_mail`` posts, in
        comment mode (the full composer of the chatter). Read-only, see
        ``mail.thread._mail_send_confirm_recipients``.

        :return: list of dicts ``{'id', 'name', 'email'}``, without duplicates
        """
        self.ensure_one()
        if (
            self.composition_mode != "comment"
            or self.subtype_is_log
            or not self.model
            or not self.model_is_thread
        ):
            return []
        records = self.env[self.model].browse(self._evaluate_res_ids()).exists()
        notify_kwargs = {
            key: True
            for key in ("notify_author", "notify_author_mention", "notify_skip_followers")
            if self[key]
        }
        subtype_id = self.subtype_id.id or self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_comment")
        result, seen = [], set()
        for record in records:
            for recipient in record._mail_send_confirm_recipients(
                partner_ids=self.partner_ids.ids,
                partner_cc_ids=self.partner_cc_ids.ids,
                subtype_id=subtype_id,
                message_type=self.message_type,
                author_id=self.author_id.id or None,
                **notify_kwargs,
            ):
                key = recipient["id"] or recipient["email"]
                if key not in seen:
                    seen.add(key)
                    result.append(recipient)
        return result
