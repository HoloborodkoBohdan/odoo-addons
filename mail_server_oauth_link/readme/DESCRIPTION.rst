With Gmail or Outlook OAuth authentication, the "Connect your Gmail/Outlook account"
button of a mail server opens the Google or Microsoft sign-in page in the browser of
the administrator. The authorization is then made for the account the administrator is
signed in to, which is the wrong mailbox when they set up someone else's address
(``sales@``, a colleague's box).

This module adds a **Get a link for the mailbox owner** button next to the stock
button, on outgoing (Gmail and Outlook) and incoming (Gmail and Outlook) mail servers.
It shows a link to copy and send to the owner of the mailbox:

* The owner opens it, signs in to Google or Microsoft with the mailbox account and
  accepts the permissions. They must be able to sign in to that mailbox, but they do
  not need an Odoo user.
* Before anything is saved, Odoo checks the account that signed in (Gmail: the verified
  address from Google; Outlook: the ``email`` of the id token asked server side, refused
  when Microsoft marks it unverified), then logs in to the mailbox with the new
  authorization, as the stock connection test does (SMTP for outgoing, IMAP for incoming
  servers). If either check fails, nothing is saved and the tokens already on the server
  stay.
* The tokens are saved on that one server only. The administrator who made the link
  gets an Odoo notification.
* The link is single use and expires (24 hours by default, 7 days at most). It is
  signed with the database secret and bound to the server and its address. It stops
  working when a new link is made, when it is revoked, when the server is archived or
  its address, host or OAuth type changes, and when its creator is no longer an
  administrator. The database keeps only a hash of its secret part.
* The secret part of the link is in the URL fragment, which browsers never send to a
  server: it does not reach server or proxy logs. The owner page keeps it in an
  HttpOnly cookie, and the OAuth ``state`` carries another one-time value that expires
  within an hour and can not open the owner page.

The module overrides the four stock callback routes ``/google_gmail/confirm``,
``/google_gmail/iap_confirm``, ``/microsoft_outlook/confirm`` and
``/microsoft_outlook/iap_confirm`` so that they accept visitors without an Odoo
session, but only for owner links; any other request still goes to the login page as
before. The redirect URIs stay the same: nothing new has to be registered at Google or
Microsoft.
