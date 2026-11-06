# Copyright 2026 Holoborodko Bohdan
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import SQL, mute_logger

from odoo.addons.cron_run_history.models import ir_cron as ir_cron_module

CORE_CRON_LOGGER = "odoo.addons.base.models.ir_cron"


@tagged("post_install", "-at_install")
class TestCronRunHistory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Run = cls.env["ir.cron.run"]
        cls.partner = cls.env["res.partner"].create({"name": "Before"})
        cls.scheduler_user = cls.env.ref("base.user_root")
        cls.cron = cls.env["ir.cron"].create({
            "name": "Cron run history test",
            "model_id": cls.env.ref("base.model_res_partner").id,
            "state": "code",
            "code": f"model.browse({cls.partner.id}).write({{'name': 'After'}})",
            "user_id": cls.scheduler_user.id,
            "interval_number": 1,
            "interval_type": "days",
            "nextcall": fields.Datetime.now() + timedelta(hours=1),
        })

    def _process(self):
        """Run the job as the scheduler does: acquire it, then process it."""
        with self.enter_registry_test_mode(), self.registry.cursor() as cron_cr:
            IrCron = self.registry["ir.cron"]
            job = IrCron._acquire_one_job(cron_cr, self.cron.id, include_not_ready=True)
            IrCron._process_job(cron_cr, job)
        return self.Run.search([("cron_id", "=", self.cron.id)], limit=1)

    def _patch_action_run(self, func):
        return patch.object(self.registry["ir.actions.server"], "run", func)

    def test_success(self):
        run = self._process()
        self.assertEqual(self.partner.name, "After")
        self.assertEqual(run.state, "success")
        self.assertEqual(run.trigger, "scheduler")
        self.assertEqual(run.user_id, self.scheduler_user)
        self.assertTrue(run.date_start)
        self.assertGreaterEqual(run.date_end, run.date_start)
        self.assertGreaterEqual(run.duration, 0)
        self.assertEqual(run.loop_count, 1)
        self.assertFalse(run.error_message)
        self.assertFalse(run.traceback)

    def test_failure_survives_rollback(self):
        self.cron.code = (
            f"model.browse({self.partner.id}).write({{'name': 'After'}})\n"
            "raise UserError('boom')"
        )
        with mute_logger(CORE_CRON_LOGGER):
            run = self._process()
        # the job's transaction was rolled back, the history row was not
        self.assertEqual(self.partner.name, "Before")
        self.assertEqual(self.cron.failure_count, 1)
        self.assertEqual(run.state, "failure")
        self.assertEqual(run.error_message, "UserError: boom")
        self.assertIn("Traceback", run.traceback)
        self.assertIn("UserError: boom", run.traceback)

    def test_manual_run(self):
        admin = self.env.ref("base.user_admin")
        with self.enter_registry_test_mode():
            self.cron.with_user(admin).method_direct_trigger()
        run = self.Run.search([("cron_id", "=", self.cron.id)])
        self.assertEqual(len(run), 1)
        self.assertEqual(run.trigger, "manual")
        self.assertEqual(run.user_id, admin)
        self.assertEqual(run.state, "success")

    def test_progress_counts(self):
        calls = []

        def run_in_batches(action):
            calls.append(action)
            if len(calls) == 1:
                action.env["ir.cron"]._commit_progress(3, remaining=2)
            else:
                action.env["ir.cron"]._commit_progress(2, remaining=0)

        with self._patch_action_run(run_in_batches):
            run = self._process()
        self.assertEqual(run.state, "success")
        self.assertEqual(run.loop_count, 2)
        self.assertEqual(run.records_done, 5)
        self.assertEqual(run.records_remaining, 0)

    def test_partially_done(self):
        calls = []

        def fail_then_stall(action):
            calls.append(action)
            if len(calls) == 1:
                action.env["ir.cron"]._commit_progress(1, remaining=4)
                raise ValueError("half way")
            action.env["ir.cron"]._commit_progress(0, remaining=4)

        with self._patch_action_run(fail_then_stall), mute_logger(CORE_CRON_LOGGER):
            run = self._process()
        self.assertEqual(run.state, "partial")
        self.assertEqual(run.loop_count, 2)
        self.assertEqual(run.records_done, 1)
        self.assertEqual(run.records_remaining, 4)
        self.assertEqual(run.error_message, "ValueError: half way")

    def test_timeout(self):
        self.env["ir.cron.progress"].create({
            "cron_id": self.cron.id,
            "done": 0,
            "remaining": 0,
            "timed_out_counter": 3,
        })
        with mute_logger(CORE_CRON_LOGGER):
            run = self._process()
        self.assertEqual(self.partner.name, "Before", "the job must not have been run")
        self.assertEqual(run.state, "timeout")
        self.assertEqual(run.loop_count, 0)
        self.assertIn("3 times", run.error_message)

    def test_stale_run_interrupted_by_next_run(self):
        stale = self.Run.create({
            "cron_id": self.cron.id,
            "date_start": fields.Datetime.now() - timedelta(hours=1),
        })
        self.assertEqual(stale.state, "running")
        run = self._process()
        self.assertNotEqual(run, stale)
        self.assertEqual(stale.state, "interrupted")
        self.assertTrue(stale.error_message)

    def test_autovacuum_interrupts_dead_runs(self):
        stale = self.Run.create({"cron_id": self.cron.id, "date_start": fields.Datetime.now()})
        self.Run._gc_interrupted_cron_runs()
        self.assertEqual(stale.state, "interrupted")

    def test_history_failure_does_not_break_the_job(self):
        broken = SQL("SELECT no_such_column")
        with (
            patch.object(ir_cron_module, "LOCK_TIMEOUT", broken),
            self.assertLogs(ir_cron_module.__name__, "WARNING") as logs,
        ):
            self._process()
        self.assertEqual(self.partner.name, "After")
        self.assertEqual(self.cron.failure_count, 0)
        self.assertFalse(self.Run.search([("cron_id", "=", self.cron.id)]))
        self.assertEqual(len(logs.records), 1)

    def test_retention_autovacuum(self):
        now = fields.Datetime.now()
        old, recent, old_running = self.Run.create([
            {"cron_id": self.cron.id, "state": "success", "date_start": now - timedelta(days=40)},
            {"cron_id": self.cron.id, "state": "failure", "date_start": now - timedelta(days=5)},
            {"cron_id": self.cron.id, "state": "running", "date_start": now - timedelta(days=40)},
        ])
        self.assertEqual(self.Run._get_retention_days(), 30)
        self.Run._gc_cron_runs()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(old_running.exists())

        params = self.env["ir.config_parameter"].sudo()
        params.set_param("cron_run_history.retention_days", "0")
        self.Run._gc_cron_runs()
        self.assertTrue(recent.exists(), "0 keeps every run")

        params.set_param("cron_run_history.retention_days", "3")
        self.Run._gc_cron_runs()
        self.assertFalse(recent.exists())

    def test_smart_button(self):
        now = fields.Datetime.now()
        self.assertEqual(self.cron.run_count, 0)
        self.assertFalse(self.cron.last_run_state)
        self.Run.create([
            {"cron_id": self.cron.id, "state": "success", "date_start": now - timedelta(hours=2)},
            {"cron_id": self.cron.id, "state": "failure", "date_start": now - timedelta(hours=1)},
        ])
        self.cron.invalidate_recordset(["run_count", "last_run_state"])
        self.assertEqual(self.cron.run_count, 2)
        self.assertEqual(self.cron.last_run_state, "failure")

        action = self.cron.action_view_runs()
        self.assertEqual(action["res_model"], "ir.cron.run")
        self.assertEqual(action["domain"], [("cron_id", "=", self.cron.id)])
        arch = self.env["ir.cron"].get_view(view_type="form")["arch"]
        self.assertIn('name="action_view_runs"', arch)
