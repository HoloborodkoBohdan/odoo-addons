# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import SQL, format_datetime
from odoo.tools.constants import GC_UNLINK_LIMIT

_logger = logging.getLogger(__name__)

RUN_STATES = [
    ("running", "Running"),
    ("success", "Success"),
    ("partial", "Partially Done"),
    ("failure", "Failed"),
    ("timeout", "Timed Out"),
    ("interrupted", "Interrupted"),
]
RETENTION_PARAM = "cron_run_history.retention_days"
DEFAULT_RETENTION_DAYS = 30
INTERRUPTED_MESSAGE = (
    "The run did not finish: the process running it stopped before the end, "
    "usually because it exceeded the time limit (limit_time_real_cron or "
    "limit_time_real) or the memory limit, or because the server restarted."
)


class IrCronRun(models.Model):
    _name = "ir.cron.run"
    _description = "Scheduled Action Run"
    _order = "date_start desc, id desc"

    # Rows are written with SQL by ir.cron (see models/ir_cron.py), in their own
    # transaction, so every field is read-only in the interface.
    cron_id = fields.Many2one(
        comodel_name="ir.cron",
        string="Scheduled Action",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    state = fields.Selection(
        selection=RUN_STATES,
        string="Status",
        required=True,
        readonly=True,
        default="running",
        help="Running: the run has started and has not finished yet.\n"
        "Success: the job completed.\n"
        "Partially Done: the job reported remaining records; Odoo runs it again soon.\n"
        "Failed: the job raised an error.\n"
        "Timed Out: the previous runs did not finish in time several times in a row, "
        "so Odoo did not execute the job and counted a failure.\n"
        "Interrupted: the process running the job stopped before the end "
        "(time limit, memory limit or server restart).",
    )
    trigger = fields.Selection(
        selection=[("scheduler", "Scheduler"), ("manual", "Run Manually")],
        string="Started By",
        required=True,
        readonly=True,
        default="scheduler",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        readonly=True,
        ondelete="set null",
        help="The user who clicked Run Manually, or the Scheduler User of the "
        "scheduled action for runs started by the scheduler.",
    )
    date_start = fields.Datetime(
        string="Start",
        required=True,
        readonly=True,
        index=True,
    )
    date_end = fields.Datetime(
        string="End",
        readonly=True,
    )
    duration = fields.Float(
        string="Duration (s)",
        digits=(16, 2),
        readonly=True,
        aggregator="avg",
    )
    loop_count = fields.Integer(
        string="Iterations",
        readonly=True,
        help="How many times the job was called during this run. Jobs that process "
        "their records in batches are called again while records remain.",
    )
    records_done = fields.Integer(
        string="Records Done",
        readonly=True,
        help="Records the job reported as processed (only for jobs that report progress).",
    )
    records_remaining = fields.Integer(
        string="Records Remaining",
        readonly=True,
        aggregator=None,
        help="Records the job reported as still to process at the end of the run.",
    )
    error_message = fields.Text(
        string="Error",
        readonly=True,
    )
    traceback = fields.Text(
        string="Traceback",
        readonly=True,
    )

    @api.depends("cron_id", "date_start")
    def _compute_display_name(self):
        for run in self:
            run.display_name = "%s (%s)" % (
                run.cron_id.display_name,
                format_datetime(self.env, run.date_start),
            )

    @api.model
    def _get_retention_days(self):
        value = self.env["ir.config_parameter"].sudo().get_param(RETENTION_PARAM)
        if not value:
            return DEFAULT_RETENTION_DAYS
        try:
            return int(value)
        except ValueError:
            _logger.warning(
                "Invalid value %r for %s, keeping runs for %s days",
                value, RETENTION_PARAM, DEFAULT_RETENTION_DAYS,
            )
            return DEFAULT_RETENTION_DAYS

    @api.autovacuum
    def _gc_cron_runs(self):
        """Delete the finished runs older than the retention period (0 = keep all)."""
        days = self._get_retention_days()
        if days <= 0:
            return 0, False
        runs = self.search(
            [
                ("date_start", "<", fields.Datetime.now() - timedelta(days=days)),
                ("state", "!=", "running"),
            ],
            limit=GC_UNLINK_LIMIT,
        )
        runs.unlink()
        return len(runs), len(runs) == GC_UNLINK_LIMIT

    @api.autovacuum
    def _gc_interrupted_cron_runs(self):
        """Close the runs left "running" by a process that died.

        A scheduled action is locked for the whole duration of its run, so a
        "running" row whose scheduled action can be locked belongs to a run
        that is over. SKIP LOCKED leaves the actions being run alone.
        """
        self.flush_model(["cron_id", "state"])
        self.env.cr.execute(SQL(
            """
            UPDATE ir_cron_run
               SET state = 'interrupted',
                   error_message = %(message)s,
                   write_uid = %(uid)s,
                   write_date = %(now)s
             WHERE state = 'running'
               AND cron_id IN (
                   SELECT id
                     FROM ir_cron
                    WHERE id IN (SELECT cron_id FROM ir_cron_run WHERE state = 'running')
                      FOR SHARE SKIP LOCKED
               )
            """,
            message=INTERRUPTED_MESSAGE,
            uid=self.env.uid,
            now=fields.Datetime.now(),
        ))
        self.invalidate_model(["state", "error_message", "write_uid", "write_date"])
