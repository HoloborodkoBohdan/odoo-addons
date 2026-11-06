Getting a link
~~~~~~~~~~~~~~

1. Go to **Settings > Technical > Email > Outgoing Mail Servers** (or **Incoming Mail
   Servers**) and open or create the server.
2. Choose **Gmail OAuth Authentication** or **Outlook OAuth Authentication** and enter
   the address of the mailbox in **Username**.
3. Click **Get a link for the mailbox owner**. The server is saved and a dialog shows
   the link with a copy button and its expiry. Copy it now: Odoo keeps no copy of it.
4. Send the link to the owner of the mailbox (chat, email, ...).

The owner opens the link and sees which address to use, clicks **Continue with Google**
or **Continue with Microsoft**, signs in with that account and accepts the permissions.
The owner must be able to sign in to the mailbox and the mailbox must allow SMTP
(outgoing server) or IMAP (incoming server) access, because Odoo logs in to it before
saving. A page tells them whether it worked. On success the server shows *Gmail Token
Valid* or *Outlook Token Valid* and you get a notification. An incoming server still
needs **Test & Confirm** to start fetching, as with the stock button.

The link works once. Clicking the button again makes a new link and the previous one
stops working; **Revoke Link** in the dialog cancels it at once. Archiving the server or
changing its address, host or OAuth type also cancels it. If the owner signs in with
another account, or the mailbox login fails, nothing is saved and they can open the same
link again until it expires.

Only members of *Administration / Settings* can get a link, and the link stops working
if its creator loses that right.

Configuration
~~~~~~~~~~~~~

Nothing new to register at Google or Microsoft: the OAuth app keeps the stock redirect
URIs ``<web.base.url>/google_gmail/confirm`` and ``<web.base.url>/microsoft_outlook/confirm``,
as for the stock button. The module overrides these two routes and the two IAP callbacks
``/google_gmail/iap_confirm`` and ``/microsoft_outlook/iap_confirm`` to let the owner in
without an Odoo session. The link points to ``<web.base.url>/mail_server_oauth_link/authorize``,
so ``web.base.url`` must be the address the owner can reach; use HTTPS so the link
cookie is marked *Secure*.

The link is valid for 24 hours. To change it, set the system parameter
``mail_server_oauth_link.validity_hours`` (1 to 168).

Without own client ID and secret, Odoo Enterprise goes through Odoo's IAP proxy, and so
does the owner link (the IAP callback receives the one-time value of the owner).
This mode could not be tested against the real IAP service. On Community, the client ID
and secret are needed, as for the stock button.

Limits
~~~~~~

* The owner page needs JavaScript (it reads the secret part of the link from the URL
  fragment).
* The address check is strict: a shared Microsoft 365 mailbox used through the account
  of a delegate can not be connected with a link (the delegate's address differs). Use
  the stock button for that case.
