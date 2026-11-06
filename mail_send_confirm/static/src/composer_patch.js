import { Composer } from "@mail/core/common/composer";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { isEmail } from "@web/core/utils/strings";
import { askMailSendConfirmation } from "./mail_send_confirm_dialog";

/** post_data keys the server needs to compute the email recipients */
const RECIPIENT_KEYS = [
    "message_type",
    "subtype_xmlid",
    "partner_ids",
    "partner_emails",
    "partner_cc_ids",
    "partner_cc_emails",
    "role_ids",
];

patch(Composer.prototype, {
    /**
     * The send button and Ctrl/Cmd+Enter both end here: ask before posting a
     * message that will be emailed.
     */
    async sendMessage() {
        if (!(await this.mailSendConfirm())) {
            return;
        }
        return super.sendMessage(...arguments);
    },

    /**
     * Whether this send may need a confirmation. Cases where the original
     * sendMessage posts nothing (editing, empty message, upload in progress,
     * invalid recipient, post in progress) are left to it.
     */
    get mailSendConfirmApplies() {
        const composer = this.props.composer;
        const thread = this.thread;
        if (
            composer.message ||
            this.props.type === "note" ||
            !thread?.id ||
            thread.model === "discuss.channel" ||
            thread.model === "mail.box" ||
            !this.state.active ||
            !this.canProcessMessage ||
            composer.attachments.some(({ uploading }) => uploading)
        ) {
            return false;
        }
        const recipients = [
            ...(composer.thread?.suggestedRecipients || []),
            ...(composer.thread?.additionalRecipients || []),
        ];
        return !recipients.some((recipient) => !isEmail(recipient.email));
    },

    /**
     * @returns {Promise<boolean>} true when the message may be posted
     */
    async mailSendConfirm() {
        if (!this.mailSendConfirmApplies) {
            return true;
        }
        if (this.mailSendConfirmPending) {
            return false; // a confirmation is already open for this composer
        }
        this.mailSendConfirmPending = true;
        try {
            const thread = this.thread;
            // the same parameters Thread.post() gives to /mail/message/post
            const params = await this.store.getMessagePostParams({
                body: this.props.composer.composerHtml,
                postData: this.postData,
                thread,
            });
            const postData = {};
            for (const key of RECIPIENT_KEYS) {
                if (key in params.post_data) {
                    postData[key] = params.post_data[key];
                }
            }
            const recipients = await rpc("/mail_send_confirm/recipients", {
                thread_model: thread.model,
                thread_id: thread.id,
                post_data: postData,
            });
            return await askMailSendConfirmation(this.store.env.services.dialog, recipients);
        } finally {
            this.mailSendConfirmPending = false;
        }
    },
});
