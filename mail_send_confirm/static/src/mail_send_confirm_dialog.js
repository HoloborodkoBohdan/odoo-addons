import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * Confirmation listing who will receive a message by email.
 */
export class MailSendConfirmDialog extends ConfirmationDialog {
    static template = "mail_send_confirm.MailSendConfirmDialog";
    static props = {
        ...ConfirmationDialog.props,
        recipients: Array,
    };
}

/**
 * Ask the user to confirm the email recipients, if there are any.
 *
 * @param {Object} dialogService
 * @param {{id: number|false, name: string, email: string}[]} recipients
 *   as returned by the server (dry run of the notification)
 * @returns {Promise<boolean>} true when the message may be sent: nobody gets
 *   it by email, or the user clicked "Send"
 */
export function askMailSendConfirmation(dialogService, recipients) {
    if (!recipients?.length) {
        return Promise.resolve(true);
    }
    return new Promise((resolve) => {
        dialogService.add(
            MailSendConfirmDialog,
            {
                recipients,
                title: _t("Send by email?"),
                confirmLabel: _t("Send"),
                cancelLabel: _t("Cancel"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            },
            // closing with the X or Escape also cancels; a resolved promise ignores it
            { onClose: () => resolve(false) }
        );
    });
}
