# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from requests import HTTPError

from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger

NO_MAIL_CTX = {"mail_create_nolog": True, "mail_create_nosubscribe": True, "mail_notrack": True}


class MailSendConfirmCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, **NO_MAIL_CTX))
        cls.mt_comment = cls.env.ref("mail.mt_comment")
        cls.mt_note = cls.env.ref("mail.mt_note")
        cls.user_sender = new_test_user(
            cls.env, "msc_sender", groups="base.group_user,base.group_partner_manager",
            email="sender@example.com", notification_type="email",
        )
        cls.user_inbox = new_test_user(
            cls.env, "msc_inbox", email="inbox@example.com", notification_type="inbox",
        )
        cls.user_email = new_test_user(
            cls.env, "msc_email", email="colleague@example.com", notification_type="email",
        )
        cls.user_portal = new_test_user(
            cls.env, "msc_portal", groups="base.group_portal", email="portal@example.com",
        )
        cls.customer, cls.other = cls.env["res.partner"].create([
            {"name": "Customer", "email": "customer@example.com"},
            {"name": "Other Contact", "email": "other@example.com"},
        ])
        # any mail.thread model works: a contact is used as the document
        cls.document = cls.env["res.partner"].create({"name": "Document"})
        cls.env.company.mail_send_confirm_mode = "external"

    def _recipients(self, document=None, **kwargs):
        document = (document or self.document).with_user(self.user_sender)
        kwargs.setdefault("subtype_id", self.mt_comment.id)
        return document._mail_send_confirm_recipients(**kwargs)

    def _ids(self, recipients):
        return {recipient["id"] for recipient in recipients}


@tagged("post_install", "-at_install")
class TestMailSendConfirm(MailSendConfirmCommon):

    def test_external_follower_only(self):
        self.document.message_subscribe(
            partner_ids=(self.customer | self.user_inbox.partner_id | self.user_email.partner_id).ids
        )
        recipients = self._recipients()
        self.assertEqual(recipients, [{
            "id": self.customer.id, "name": "Customer", "email": "customer@example.com",
        }])

    def test_internal_followers_only(self):
        self.document.message_subscribe(
            partner_ids=(self.user_inbox.partner_id | self.user_email.partner_id).ids
        )
        self.assertEqual(self._recipients(), [])

    def test_mode_all_adds_internal_email_recipients(self):
        self.env.company.mail_send_confirm_mode = "all"
        self.document.message_subscribe(
            partner_ids=(self.customer | self.user_inbox.partner_id | self.user_email.partner_id).ids
        )
        # inbox users get no email, the author never gets their own message
        self.assertEqual(
            self._ids(self._recipients()),
            {self.customer.id, self.user_email.partner_id.id},
        )
        self.document.message_subscribe(partner_ids=self.user_sender.partner_id.ids)
        self.assertNotIn(self.user_sender.partner_id.id, self._ids(self._recipients()))

    def test_mode_never(self):
        self.env.company.mail_send_confirm_mode = "never"
        self.document.message_subscribe(partner_ids=self.customer.ids)
        self.assertEqual(self._recipients(partner_ids=self.other.ids), [])

    def test_explicit_partners(self):
        # suggested / added recipients and mentions are not followers
        recipients = self._recipients(partner_ids=(self.other | self.user_email.partner_id).ids)
        self.assertEqual(self._ids(recipients), {self.other.id})

    def test_cc_partners(self):
        recipients = self._recipients(
            partner_ids=self.other.ids,
            partner_cc_ids=(self.customer | self.other | self.user_email.partner_id).ids,
        )
        self.assertEqual(sorted(self._ids(recipients)), sorted({self.customer.id, self.other.id}))
        self.assertEqual(len(recipients), 2)

    def test_cc_emails_without_contact(self):
        recipients = self._recipients(
            emails=["new.person@example.com"],
            cc_emails=["New.Person@example.com", "cc.person@example.com"],
        )
        self.assertEqual(
            sorted(recipient["email"] for recipient in recipients),
            ["cc.person@example.com", "new.person@example.com"],
        )

    def test_portal_user_is_external(self):
        self.document.message_subscribe(partner_ids=self.user_portal.partner_id.ids)
        self.assertEqual(self._ids(self._recipients()), {self.user_portal.partner_id.id})

    def test_note_never_asks(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        self.assertEqual(self._recipients(subtype_id=self.mt_note.id, partner_ids=self.other.ids), [])
        self.assertEqual(self._recipients(subtype_id=False, partner_ids=self.other.ids), [])

    def test_follower_not_subscribed_to_discussions(self):
        self.document.message_subscribe(partner_ids=self.customer.ids, subtype_ids=self.mt_note.ids)
        self.assertEqual(self._recipients(), [])

    def test_archived_partner_skipped(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        self.customer.active = False
        self.assertEqual(self._recipients(), [])

    def test_skip_followers(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        recipients = self._recipients(partner_ids=self.other.ids, notify_skip_followers=True)
        self.assertEqual(self._ids(recipients), {self.other.id})

    def test_emails_without_contact(self):
        partner_count = self.env["res.partner"].with_context(active_test=False).search_count([])
        recipients = self._recipients(emails=['"New Person" <New.Person@example.com>', "customer@example.com"])
        self.assertEqual(self.env["res.partner"].with_context(active_test=False).search_count([]), partner_count)
        self.assertIn({"id": self.customer.id, "name": "Customer", "email": "customer@example.com"}, recipients)
        self.assertIn({"id": False, "name": "New Person", "email": "new.person@example.com"}, recipients)
        self.assertEqual(len(recipients), 2)

    def test_emails_without_contact_no_creation_right(self):
        # /mail/message/post does not create the contact, so nobody gets the email
        self.user_sender.group_ids -= self.env.ref("base.group_partner_manager")
        if self.user_sender.has_group("base.group_partner_manager"):
            self.skipTest("Contact creation is implied by another group of the user")
        self.assertEqual(self._recipients(emails=["new.person@example.com"]), [])

    def test_dry_run_has_no_side_effect(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        models = ["mail.message", "mail.mail", "mail.followers", "mail.notification", "res.partner"]
        before = {model: self.env[model].sudo().search_count([]) for model in models}
        self._recipients(partner_ids=self.other.ids, emails=["new.person@example.com"])
        after = {model: self.env[model].sudo().search_count([]) for model in models}
        self.assertEqual(before, after)

    def test_same_recipients_as_message_post(self):
        self.env.company.mail_send_confirm_mode = "all"
        self.document.message_subscribe(
            partner_ids=(self.customer | self.user_inbox.partner_id | self.user_portal.partner_id).ids
        )
        expected = self._ids(self._recipients(partner_ids=(self.other | self.user_email.partner_id).ids))
        message = self.document.with_user(self.user_sender).message_post(
            body="Hello", message_type="comment", subtype_xmlid="mail.mt_comment",
            partner_ids=(self.other | self.user_email.partner_id).ids,
        )
        emailed = message.notification_ids.filtered(lambda n: n.notification_type == "email").res_partner_id
        self.assertEqual(expected, set(emailed.ids))
        self.assertEqual(
            expected,
            {self.customer.id, self.user_portal.partner_id.id, self.other.id, self.user_email.partner_id.id},
        )

    def test_composer_comment(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        composer = self.env["mail.compose.message"].with_user(self.user_sender).with_context(
            default_composition_mode="comment",
            default_model="res.partner",
            default_res_ids=self.document.ids,
            default_subtype_xmlid="mail.mt_comment",
            default_partner_ids=(self.other | self.user_email.partner_id).ids,
        ).create({"body": "<p>Hello</p>"})
        self.assertEqual(
            self._ids(composer.mail_send_confirm_get_recipients()),
            {self.customer.id, self.other.id},
        )

    def test_composer_log_note(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        composer = self.env["mail.compose.message"].with_user(self.user_sender).with_context(
            default_composition_mode="comment",
            default_model="res.partner",
            default_res_ids=self.document.ids,
            default_subtype_xmlid="mail.mt_note",
        ).create({"body": "<p>Internal</p>"})
        self.assertEqual(composer.mail_send_confirm_get_recipients(), [])


@tagged("post_install", "-at_install")
class TestMailSendConfirmRoute(HttpCase, MailSendConfirmCommon):

    def test_route(self):
        self.document.message_subscribe(partner_ids=self.customer.ids)
        self.authenticate("msc_sender", "msc_sender")
        recipients = self.make_jsonrpc_request("/mail_send_confirm/recipients", {
            "thread_model": "res.partner",
            "thread_id": self.document.id,
            "post_data": {
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
                "partner_ids": [self.other.id],
                "partner_emails": ["new.person@example.com"],
                "partner_cc_ids": [self.user_portal.partner_id.id],
            },
        })
        self.assertEqual(
            {(recipient["id"], recipient["email"]) for recipient in recipients},
            {
                (self.customer.id, "customer@example.com"),
                (self.other.id, "other@example.com"),
                (False, "new.person@example.com"),
                (self.user_portal.partner_id.id, "portal@example.com"),
            },
        )
        note = self.make_jsonrpc_request("/mail_send_confirm/recipients", {
            "thread_model": "res.partner",
            "thread_id": self.document.id,
            "post_data": {"subtype_xmlid": "mail.mt_note", "partner_ids": [self.other.id]},
        })
        self.assertEqual(note, [])

    @mute_logger("odoo.http")
    def test_route_rejects_non_thread_model(self):
        self.authenticate("msc_sender", "msc_sender")
        try:
            self.make_jsonrpc_request("/mail_send_confirm/recipients", {
                "thread_model": "res.country",
                "thread_id": 1,
                "post_data": {"subtype_xmlid": "mail.mt_comment"},
            })
        except (JsonRpcException, HTTPError):
            pass
        else:
            self.fail("A model without chatter must be refused")
