import { MailComposerFormController } from "@mail/chatter/web/mail_composer_form";
import { patch } from "@web/core/utils/patch";
import { askMailSendConfirmation } from "./mail_send_confirm_dialog";

patch(MailComposerFormController.prototype, {
    /**
     * "Send" in the full composer opened from the chatter: once the wizard is
     * saved, ask who would receive the message by email and confirm.
     * "Send by email" buttons of business documents open the same wizard
     * without the chatter context and are left alone.
     */
    async beforeExecuteActionButton(clickParams) {
        const result = await super.beforeExecuteActionButton(...arguments);
        const record = this.model.root;
        if (
            result === false ||
            clickParams.name !== "action_send_mail" ||
            !this.props.context?.is_full_composer ||
            record.data.composition_mode !== "comment" ||
            record.data.subtype_is_log ||
            !record.resId
        ) {
            return result;
        }
        const recipients = await this.orm.call(
            "mail.compose.message",
            "mail_send_confirm_get_recipients",
            [[record.resId]]
        );
        if (!(await askMailSendConfirmation(this.dialogService, recipients))) {
            return false;
        }
        return result;
    },
});
