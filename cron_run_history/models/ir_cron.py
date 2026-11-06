# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import contextvars
import logging
import time
import traceback

from odoo import api, fields, models
from odoo.tools import SQL

from odoo.addons.base.models.ir_cron import CONSECUTIVE_TIMEOUT_FOR_FAILURE, CompletionStatus

from .ir_cron_run import INTERRUPTED_MESSAGE, RUN_STATES

_logger = logging.getLogger(__name__)

# The run being processed: set by _process_job, filled in by the methods it
# calls (_add_progress, _callback, _update_failure_count).
_current_run = contextvars.ContextVar("cron_run_history_current_run", default=None)
# The user who clicked "Run Manually", set around method_direct_trigger.
_manual_uid = contextvars.ContextVar("cron_run_history_manual_uid", default=None)

COMPLETION_STATES = {
    CompletionStatus.FULLY_DONE: "success",
    CompletionStatus.PARTIALLY_DONE: "partial",
    CompletionStatus.FAILED: "failure",
}
TIMEOUT_MESSAGE = (
    "Not executed: the job timed out %s times in a row, so Odoo counted this "
    "run as a failure without running it."
)
# The history is written with its own cursor while the scheduler's cursor holds
# the lock on the cron row; never wait long for a lock there.
LOCK_TIMEOUT = SQL("SET LOCAL lock_timeout = '5s'")


def _record_error(run, exc):
    run["error"] = f"{type(exc).__name__}: {exc}"
    run["traceback"] = traceback.format_exc()


class IrCron(models.Model):
    _inherit = "ir.cron"

    run_count = fields.Integer(
        string="Runs",
        compute="_compute_run_stats",
        groups="base.group_system",
    )
    last_run_state = fields.Selection(
        selection=RUN_STATES,
        string="Last Run Status",
        compute="_compute_run_stats",
        groups="base.group_system",
    )

    def _compute_run_stats(self):
        Run = self.env["ir.cron.run"]
        counts = dict(Run._read_group(
            [("cron_id", "in", self._origin.ids)], ["cron_id"], ["__count"],
        ))
        for cron in self:
            cron.run_count = counts.get(cron._origin, 0)
            cron.last_run_state = Run.search([("cron_id", "=", cron._origin.id)], limit=1).state

    def action_view_runs(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("cron_run_history.ir_cron_run_action")
        action["domain"] = [("cron_id", "=", self.id)]
        return action

    def method_direct_trigger(self):
        token = _manual_uid.set(self.env.uid)
        try:
            return super().method_direct_trigger()
        finally:
            _manual_uid.reset(token)

    @classmethod
    def _process_job(cls, cron_cr, job):
        manual_uid = _manual_uid.get()
        run = {
            "cron_id": job["id"],
            "trigger": "manual" if manual_uid else "scheduler",
            "user_id": manual_uid or job["user_id"],
            # same test as the one Odoo makes before deciding not to run the job
            "timed_out": (
                job["timed_out_counter"] >= CONSECUTIVE_TIMEOUT_FOR_FAILURE and not job["done"]
            ),
            "timed_out_counter": job["timed_out_counter"],
            "status": None,
            "progress_ids": [],
            "error": None,
            "traceback": None,
        }
        run["id"] = cls._cron_run_start(run)
        start = time.monotonic()
        token = _current_run.set(run)
        try:
            super()._process_job(cron_cr, job)
        except Exception as exc:
            _record_error(run, exc)
            run["status"] = CompletionStatus.FAILED
            raise
        finally:
            _current_run.reset(token)
            cls._cron_run_finish(run, time.monotonic() - start)

    def _add_progress(self, *, timed_out_counter=None):
        cron, progress = super()._add_progress(timed_out_counter=timed_out_counter)
        run = _current_run.get()
        if run is not None and run["cron_id"] == self.id:
            run["progress_ids"].append(progress.id)
        return cron, progress

    def _callback(self, cron_name, server_action_id):
        try:
            return super()._callback(cron_name, server_action_id)
        except Exception as exc:
            run = _current_run.get()
            if run is not None and run["cron_id"] == self.id:
                _record_error(run, exc)
            raise

    @api.model
    def _update_failure_count(self, job, status):
        run = _current_run.get()
        if run is not None and run["cron_id"] == job["id"]:
            run["status"] = status
        return super()._update_failure_count(job, status)

    @classmethod
    def _cron_run_start(cls, run):
        """Insert the "running" row in its own transaction and return its id.

        Runs of the same scheduled action still "running" are left over by a
        process that died: the cron row is locked by this run, so no other run
        of it can be in progress. They are marked as interrupted.

        Never raises: a history failure must not stop the scheduled action.
        """
        now = fields.Datetime.now()
        try:
            with cls.pool.cursor() as cr:
                cr.execute(LOCK_TIMEOUT, log_exceptions=False)
                cr.execute(SQL(
                    """
                    WITH stale AS (
                        UPDATE ir_cron_run
                           SET state = 'interrupted',
                               error_message = %(interrupted)s,
                               write_uid = %(uid)s,
                               write_date = %(now)s
                         WHERE id IN (
                               SELECT id
                                 FROM ir_cron_run
                                WHERE cron_id = %(cron_id)s AND state = 'running'
                                  FOR UPDATE SKIP LOCKED
                         )
                    )
                    INSERT INTO ir_cron_run (
                        cron_id, state, trigger, user_id, date_start,
                        create_uid, create_date, write_uid, write_date
                    )
                    VALUES (
                        %(cron_id)s, 'running', %(trigger)s, %(uid)s, %(now)s,
                        %(uid)s, %(now)s, %(uid)s, %(now)s
                    )
                    RETURNING id
                    """,
                    interrupted=INTERRUPTED_MESSAGE,
                    cron_id=run["cron_id"],
                    trigger=run["trigger"],
                    uid=run["user_id"],
                    now=now,
                ), log_exceptions=False)
                return cr.fetchone()[0]
        except Exception:
            _logger.warning(
                "Could not record the start of scheduled action %s", run["cron_id"], exc_info=True,
            )
            return None

    @classmethod
    def _cron_run_finish(cls, run, duration):
        """Write the outcome of the run in its own transaction.

        The counts come from the ir.cron.progress rows of the run, which the
        job's own transaction has committed by now. Never raises.
        """
        if not run["id"]:
            return
        if run["timed_out"]:
            state = "timeout"
            error = TIMEOUT_MESSAGE % run["timed_out_counter"]
        else:
            state = COMPLETION_STATES.get(run["status"], "failure")
            error = run["error"]
        try:
            with cls.pool.cursor() as cr:
                cr.execute(LOCK_TIMEOUT, log_exceptions=False)
                cr.execute(SQL(
                    """
                    UPDATE ir_cron_run
                       SET state = %(state)s,
                           date_end = %(now)s,
                           duration = %(duration)s,
                           loop_count = %(loop_count)s,
                           records_done = COALESCE(progress.done, 0),
                           records_remaining = COALESCE(progress.remaining, 0),
                           error_message = %(error)s,
                           traceback = %(traceback)s,
                           write_date = %(now)s
                      FROM (
                           SELECT SUM(done) AS done,
                                  (ARRAY_AGG(remaining ORDER BY id DESC))[1] AS remaining
                             FROM ir_cron_progress
                            WHERE id = ANY(%(progress_ids)s::int[])
                      ) AS progress
                     WHERE ir_cron_run.id = %(id)s
                    """,
                    state=state,
                    now=fields.Datetime.now(),
                    duration=round(duration, 2),
                    loop_count=len(run["progress_ids"]),
                    error=error,
                    traceback=run["traceback"],
                    progress_ids=run["progress_ids"],
                    id=run["id"],
                ), log_exceptions=False)
        except Exception:
            _logger.warning(
                "Could not record the end of scheduled action %s", run["cron_id"], exc_info=True,
            )
