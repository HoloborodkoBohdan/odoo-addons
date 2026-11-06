In the chatter, *Send message* emails the message to the followers of the
record, while *Log note* keeps it internal. Odoo sends at once, without asking,
so a note meant for colleagues sometimes reaches the customer.

This module asks for a confirmation before a chatter message is emailed to
someone outside the company, and lists exactly who will receive it.

Features:

* A confirmation dialog with the name and email address of every external
  recipient, with *Send* and *Cancel*
* Covers the *Send* button and Ctrl+Enter (Cmd+Enter on macOS) in the
  chatter, and *Send* in the full composer opened from the chatter
* Recipients are computed on the server the way Odoo computes them when it
  posts the message: followers subscribed to discussions, added and suggested
  recipients (To and Cc), mentioned contacts, new email addresses; the author and archived
  contacts are left out
* External means a contact without an internal user: customers, vendors,
  portal users
* No dialog when only internal users are notified, and never for log notes
* A company setting: confirm for external recipients (default), for any email
  recipient, or never
