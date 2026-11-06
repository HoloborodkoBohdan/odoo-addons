Odoo keeps no record of the runs of its scheduled actions: a scheduled action
only shows its next and last execution dates and a counter of consecutive
failures, and the error of a failed run goes to the server log, which users of
Odoo Online and Odoo.sh often cannot read. This module records every run of
every scheduled action.

For each run it keeps:

* the scheduled action, start, end and duration
* the status: *Running*, *Success*, *Partially Done* (the job reported remaining
  records and will run again soon), *Failed*, *Timed Out* (Odoo did not run the
  job because its previous runs timed out several times in a row) or
  *Interrupted* (the process running the job stopped before the end: time
  limit, memory limit or server restart)
* the number of iterations and, for jobs that report their progress, the
  number of records done and remaining
* the error message and the full traceback when the job fails
* how the run was started (by the scheduler or with *Run Manually*) and the user

The history is written in its own database transaction, so the run of a failed
job stays recorded although Odoo rolls back the job's changes. Writing the
history never stops a scheduled action: if it fails, a warning is logged and
the job runs as usual.

Runs older than 30 days are deleted automatically; the period can be changed.
