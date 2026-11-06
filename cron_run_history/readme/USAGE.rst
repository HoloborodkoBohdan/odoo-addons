Viewing the runs
~~~~~~~~~~~~~~~~

* Go to **Settings > Technical > Automation > Scheduled Action Runs** to see the
  runs of every scheduled action, the most recent first
* Use the *Failed* filter to see the failed, timed out and interrupted runs, and
  group the runs by *Scheduled Action*, *Status*, *Started By* or *Day*
* Open a run to see its error message and traceback

From a scheduled action
~~~~~~~~~~~~~~~~~~~~~~~

* Open a scheduled action in **Settings > Technical > Automation > Scheduled
  Actions**: the *Runs* button at the top shows how many runs are recorded and
  the status of the last one; click it to list the runs of that action
* A run started with *Run Manually* is recorded with *Started By* set to *Run
  Manually* and the user who clicked the button

Retention
~~~~~~~~~

Runs older than 30 days are deleted by the daily *Base: Auto-vacuum internal
data* scheduled action. To change the period, activate the developer mode, go to
**Settings > Technical > Parameters > System Parameters** and set
``cron_run_history.retention_days`` to the number of days to keep; ``0`` keeps
every run.

The same scheduled action marks as *Interrupted* the runs still shown as
*Running* whose process has stopped (a run of the same scheduled action does it
too when it starts).
