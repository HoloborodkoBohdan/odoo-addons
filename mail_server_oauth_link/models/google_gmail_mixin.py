# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models

from .mail_server_oauth_link_mixin import CONTEXT_KEY


class GoogleGmailMixin(models.AbstractModel):
    _inherit = "google.gmail.mixin"

    def _get_gmail_csrf_token(self):
        """Put the owner flow value in the OAuth state instead of the stock token.

        Only while the owner page builds its sign-in URL, and only when the
        value really is a valid flow of this very server.
        """
        flow = self.env.context.get(CONTEXT_KEY)
        if flow and "oauth_link_flow_hash" in self._fields and self._oauth_link_owns_flow(flow, "gmail"):
            return flow
        return super()._get_gmail_csrf_token()
