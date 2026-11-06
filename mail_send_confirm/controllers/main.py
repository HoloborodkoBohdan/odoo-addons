# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request


class MailSendConfirmController(http.Controller):

    @http.route("/mail_send_confirm/recipients", methods=["POST"], type="jsonrpc", auth="user")
    def mail_send_confirm_recipients(self, thread_model, thread_id, post_data):
        """Who would receive by email the message that ``/mail/message/post``
        is about to post with ``post_data`` (the same payload, built by the
        chatter composer). Read-only, see ``_mail_send_confirm_recipients``."""
        if thread_model not in request.env or not isinstance(
            request.env[thread_model], request.env.registry["mail.thread"]
        ):
            raise NotFound()
        thread = request.env[thread_model]._get_thread_with_access(int(thread_id), mode="read")
        if not thread or not request.env.user._is_internal():
            return []
        Partner = request.env["res.partner"]
        partners = Partner.browse(int(pid) for pid in post_data.get("partner_ids") or [])
        partners_cc = Partner.browse(int(pid) for pid in post_data.get("partner_cc_ids") or [])
        role_ids = post_data.get("role_ids")
        if role_ids:
            # sudo - res.users: getting partners linked to the role is allowed (as in mail)
            partners |= request.env["res.users"].sudo().search_fetch(
                [("role_ids", "in", role_ids)], ["partner_id"],
            ).partner_id
        # same partner filter as /mail/message/post for internal users
        partners = partners.filtered(lambda p: p.has_access("read"))
        partners_cc = partners_cc.filtered(lambda p: p.has_access("read"))
        subtype_id = request.env["ir.model.data"]._xmlid_to_res_id(
            post_data.get("subtype_xmlid") or "mail.mt_note", raise_if_not_found=False,
        )
        return thread._mail_send_confirm_recipients(
            partner_ids=partners.ids,
            partner_cc_ids=partners_cc.ids,
            emails=post_data.get("partner_emails") or [],
            cc_emails=post_data.get("partner_cc_emails") or [],
            subtype_id=subtype_id,
            message_type=post_data.get("message_type") or "comment",
        )
