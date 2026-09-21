import calendar
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "codex-maint"
LOADER = importlib.machinery.SourceFileLoader("codex_maint", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
codex_maint = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(codex_maint)


def credit(credit_id, expires_at, status="available"):
    return {"id": credit_id, "expiresAt": expires_at, "status": status}


def rate_limits(credits=(), primary=None, secondary=None):
    snapshot = {"limitId": "codex"}

    if primary is not None:
        snapshot["primary"] = primary

    if secondary is not None:
        snapshot["secondary"] = secondary

    return {
        "rateLimitResetCredits": {
            "availableCount": len(credits),
            "credits": list(credits),
        },
        "rateLimits": snapshot,
        "rateLimitsByLimitId": {"codex": snapshot},
    }


def window(used_percent, duration_mins):
    return {
        "resetsAt": 1789977628,
        "usedPercent": used_percent,
        "windowDurationMins": duration_mins,
    }


def parse_oncalendar(text):
    parsed = time.strptime(text, "%Y-%m-%d %H:%M:%S UTC")
    return calendar.timegm(parsed)


class FakeServer:
    def __init__(self, limits):
        self.limits = limits
        self.consumed = []

    def rate_limits(self):
        return self.limits

    def consume_reset_credit(self, credit_id):
        self.consumed.append(credit_id)
        return {"status": "consumed"}


class CodexMaintTestCase(unittest.TestCase):
    """Patch logging and systemd so tests stay hermetic."""

    def setUp(self):
        self.logs = []
        patcher = mock.patch.object(codex_maint, "log", self.logs.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    @contextlib.contextmanager
    def fake_app_server(self, server):
        """Replace codex_app_server() and record how often codex was started."""
        servers = self.app_servers = []

        @contextlib.contextmanager
        def factory(*_args, **_kwargs):
            servers.append(server)
            yield server

        with mock.patch.object(codex_maint, "codex_app_server", factory):
            yield servers

    @contextlib.contextmanager
    def fake_systemctl(self, stdout="[]", returncode=0):
        result = mock.Mock(stdout=stdout, stderr="", returncode=returncode)
        calls = mock.Mock(return_value=result)

        with mock.patch.object(codex_maint, "systemctl", calls):
            yield calls


class ResetIdempotencyKeyTest(CodexMaintTestCase):
    def test_matches_documented_formula(self):
        expected = (
            "auto-reset-" + hashlib.sha256(b"RateLimitResetCredit_f7").hexdigest()[:32]
        )

        self.assertEqual(
            codex_maint.reset_idempotency_key("RateLimitResetCredit_f7"),
            expected,
        )

    def test_is_stable_and_credit_specific(self):
        first = codex_maint.reset_idempotency_key("RateLimitResetCredit_one")
        again = codex_maint.reset_idempotency_key("RateLimitResetCredit_one")
        other = codex_maint.reset_idempotency_key("RateLimitResetCredit_two")

        self.assertEqual(first, again)
        self.assertNotEqual(first, other)


class AvailableCreditsTest(CodexMaintTestCase):
    def test_sorts_by_expiry(self):
        limits = rate_limits(
            [
                credit("late", 3000),
                credit("soon", 1000),
                credit("middle", 2000),
            ]
        )

        ids = [c["id"] for c in codex_maint.available_credits(limits)]

        self.assertEqual(ids, ["soon", "middle", "late"])

    def test_skips_credits_that_are_not_available(self):
        limits = rate_limits(
            [
                credit("gone", 1000, status="consumed"),
                credit("ready", 2000),
            ]
        )

        ids = [c["id"] for c in codex_maint.available_credits(limits)]

        self.assertEqual(ids, ["ready"])

    def test_tolerates_missing_fields(self):
        self.assertEqual(codex_maint.available_credits({}), [])
        self.assertEqual(
            codex_maint.available_credits({"rateLimitResetCredits": None}),
            [],
        )

    def test_credit_without_status_counts_as_available(self):
        limits = rate_limits([{"id": "legacy", "expiresAt": 1000}])

        self.assertEqual(
            [c["id"] for c in codex_maint.available_credits(limits)],
            ["legacy"],
        )


class FindFiveHourWindowTest(CodexMaintTestCase):
    def test_prefers_multi_bucket_form(self):
        limits = rate_limits(primary=window(10, 300))
        limits["rateLimits"] = {"primary": window(99, 300)}

        self.assertEqual(codex_maint.find_five_hour_window(limits)["usedPercent"], 10)

    def test_falls_back_to_legacy_form(self):
        limits = {"rateLimits": {"primary": window(7, 300)}}

        self.assertEqual(codex_maint.find_five_hour_window(limits)["usedPercent"], 7)

    def test_finds_window_in_secondary_slot(self):
        limits = rate_limits(primary=window(46, 10080), secondary=window(0, 300))

        self.assertEqual(codex_maint.find_five_hour_window(limits)["usedPercent"], 0)

    def test_returns_none_without_five_hour_window(self):
        limits = rate_limits(primary=window(46, 10080))

        self.assertIsNone(codex_maint.find_five_hour_window(limits))


class PendingScheduleTest(CodexMaintTestCase):
    def test_returns_timer_with_upcoming_elapse(self):
        stdout = json.dumps(
            [{"unit": "codex-maint-consume.timer", "next": 1789999200000000}]
        )

        with self.fake_systemctl(stdout=stdout):
            timer = codex_maint.pending_schedule()

        self.assertEqual(timer["unit"], "codex-maint-consume.timer")

    def test_ignores_timer_that_already_elapsed(self):
        stdout = json.dumps([{"unit": "codex-maint-consume.timer", "next": None}])

        with self.fake_systemctl(stdout=stdout):
            self.assertIsNone(codex_maint.pending_schedule())

    def test_ignores_missing_timer(self):
        with self.fake_systemctl(stdout="[]"):
            self.assertIsNone(codex_maint.pending_schedule())

    def test_reports_systemctl_failure(self):
        with self.fake_systemctl(stdout="", returncode=1):
            with self.assertRaisesRegex(RuntimeError, "list-timers failed"):
                codex_maint.pending_schedule()

    def test_reports_unparseable_systemctl_output(self):
        with self.fake_systemctl(stdout="not json"):
            with self.assertRaisesRegex(RuntimeError, "unexpected"):
                codex_maint.pending_schedule()


class WriteScheduleUnitsTest(CodexMaintTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        patcher = mock.patch.object(codex_maint, "UNIT_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

        patcher = mock.patch.object(
            codex_maint.shutil, "which", return_value="/opt/codex/bin/codex"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_service_runs_this_script_with_consume(self):
        service, timer = codex_maint.write_schedule_units(
            "RateLimitResetCredit_f7", 1791090272
        )

        self.assertEqual(service.name, "codex-maint-consume.service")
        self.assertEqual(timer.name, "codex-maint-consume.timer")

        text = service.read_text()

        self.assertIn(f"ExecStart={SCRIPT.resolve()}", text)
        self.assertIn("--consume RateLimitResetCredit_f7", text)
        self.assertIn(
            "Environment=PATH=/opt/codex/bin:%h/.local/bin:/usr/local/bin:"
            "/usr/bin:/bin",
            text,
        )
        self.assertIn("Type=oneshot", text)

    def test_timer_fires_once_without_catch_up(self):
        _service, timer = codex_maint.write_schedule_units(
            "RateLimitResetCredit_f7", 1791090272
        )

        text = timer.read_text()

        self.assertIn("OnCalendar=2026-10-04 05:04:32 UTC", text)
        self.assertNotIn("Persistent", text)
        self.assertIn("RemainAfterElapse=false", text)
        self.assertIn("WantedBy=timers.target", text)


class CommandScheduleTest(CodexMaintTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        patcher = mock.patch.object(codex_maint, "UNIT_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_codex_when_timer_is_already_pending(self):
        timer = {"unit": "codex-maint-consume.timer", "next": 1789999200000000}

        with mock.patch.object(codex_maint, "pending_schedule", return_value=timer):
            with mock.patch.object(
                codex_maint, "codex_app_server", side_effect=AssertionError
            ):
                codex_maint.command_schedule()

        self.assertTrue(any("already pending" in line for line in self.logs))

    def test_schedules_next_expiring_credit(self):
        expires_at = time.time() + 3600
        limits = rate_limits(
            [credit("later", expires_at + 60), credit("next", expires_at)]
        )
        server = FakeServer(limits)
        stdout = "[]"

        with mock.patch.object(codex_maint, "pending_schedule", return_value=None):
            with self.fake_app_server(server):
                with self.fake_systemctl(stdout=stdout) as systemctl:
                    codex_maint.command_schedule()

        service = Path(self.tmp.name) / "codex-maint-consume.service"
        timer = Path(self.tmp.name) / "codex-maint-consume.timer"

        self.assertIn("--consume next", service.read_text())

        elapsed = parse_oncalendar(
            [
                line
                for line in timer.read_text().splitlines()
                if line.startswith("OnCalendar=")
            ][0].removeprefix("OnCalendar=")
        )
        self.assertAlmostEqual(
            elapsed, expires_at - codex_maint.SCHEDULE_LEAD_SECONDS, delta=2
        )

        units = [call.args[0] for call in systemctl.call_args_list]
        self.assertEqual(units, ["daemon-reload", "enable", "restart"])
        self.assertEqual(
            systemctl.call_args_list[-1].args[1],
            "codex-maint-consume.timer",
        )

    def test_does_nothing_without_available_credits(self):
        with mock.patch.object(codex_maint, "pending_schedule", return_value=None):
            with self.fake_app_server(FakeServer(rate_limits())):
                with self.fake_systemctl() as systemctl:
                    codex_maint.command_schedule()

        self.assertEqual(systemctl.call_count, 0)
        self.assertTrue(any("no available banked reset" in line for line in self.logs))

    def test_clamps_elapse_time_that_already_passed(self):
        # A credit with less than the lead time left must still be consumed
        # eventually, so the timer is scheduled for the near future.
        limits = rate_limits([credit("fading", time.time() + 60)])
        stdout = "[]"

        with mock.patch.object(codex_maint, "pending_schedule", return_value=None):
            with self.fake_app_server(FakeServer(limits)):
                with self.fake_systemctl(stdout=stdout):
                    codex_maint.command_schedule()

        timer = Path(self.tmp.name) / "codex-maint-consume.timer"
        elapsed = parse_oncalendar(
            [
                line
                for line in timer.read_text().splitlines()
                if line.startswith("OnCalendar=")
            ][0].removeprefix("OnCalendar=")
        )

        self.assertGreater(elapsed, time.time())
        self.assertLess(elapsed, time.time() + 120)


class CommandConsumeTest(CodexMaintTestCase):
    def test_consumes_soon_expiring_credit(self):
        limits = rate_limits([credit("soon", time.time() + 600)])
        server = FakeServer(limits)

        with self.fake_app_server(server):
            result = codex_maint.command_consume("soon", force=False)

        self.assertEqual(result, 0)
        self.assertEqual(server.consumed, ["soon"])

    def test_refuses_credit_with_more_than_an_hour_left(self):
        limits = rate_limits([credit("healthy", time.time() + 7200)])
        server = FakeServer(limits)

        with self.fake_app_server(server):
            result = codex_maint.command_consume("healthy", force=False)

        self.assertEqual(result, 3)
        self.assertEqual(server.consumed, [])
        self.assertTrue(any("--force" in line for line in self.logs))

    def test_force_consumes_credit_with_more_than_an_hour_left(self):
        limits = rate_limits([credit("healthy", time.time() + 7200)])
        server = FakeServer(limits)

        with self.fake_app_server(server):
            result = codex_maint.command_consume("healthy", force=True)

        self.assertEqual(result, 0)
        self.assertEqual(server.consumed, ["healthy"])

    def test_noop_when_credit_is_gone(self):
        limits = rate_limits([credit("other", time.time() + 600)])
        server = FakeServer(limits)

        with self.fake_app_server(server):
            result = codex_maint.command_consume("missing", force=True)

        self.assertEqual(result, 0)
        self.assertEqual(server.consumed, [])
        self.assertTrue(any("no longer available" in line for line in self.logs))

    def test_noop_for_expired_credit_that_server_no_longer_lists(self):
        server = FakeServer(rate_limits())

        with self.fake_app_server(server):
            result = codex_maint.command_consume("expired", force=False)

        self.assertEqual(result, 0)
        self.assertEqual(server.consumed, [])


class CommandStartWindowTest(CodexMaintTestCase):
    def test_starts_window_when_idle(self):
        limits = rate_limits(primary=window(0, 300))

        with self.fake_app_server(FakeServer(limits)):
            with mock.patch.object(codex_maint, "start_window") as starter:
                result = codex_maint.command_start_window()

        self.assertEqual(result, 0)
        starter.assert_called_once_with()

    def test_does_not_touch_active_window(self):
        limits = rate_limits(primary=window(12, 300))

        with self.fake_app_server(FakeServer(limits)):
            with mock.patch.object(codex_maint, "start_window") as starter:
                result = codex_maint.command_start_window()

        self.assertEqual(result, 0)
        starter.assert_not_called()
        self.assertTrue(any("already active" in line for line in self.logs))

    def test_reports_missing_window(self):
        limits = rate_limits(primary=window(12, 10080))

        with self.fake_app_server(FakeServer(limits)):
            with mock.patch.object(codex_maint, "start_window") as starter:
                result = codex_maint.command_start_window()

        self.assertEqual(result, 2)
        starter.assert_not_called()


class ParseArgsTest(CodexMaintTestCase):
    @contextlib.contextmanager
    def quiet_stderr(self):
        """argparse prints usage to stderr before raising SystemExit."""
        with contextlib.redirect_stderr(io.StringIO()):
            yield

    def test_default_action(self):
        args = codex_maint.parse_args([])

        self.assertFalse(args.schedule)
        self.assertIsNone(args.consume)
        self.assertFalse(args.start_window)

    def test_consume_takes_a_credit_id(self):
        args = codex_maint.parse_args(["--consume", "RateLimitResetCredit_x"])

        self.assertEqual(args.consume, "RateLimitResetCredit_x")
        self.assertFalse(args.force)

    def test_actions_are_mutually_exclusive(self):
        with self.quiet_stderr():
            with self.assertRaises(SystemExit):
                codex_maint.parse_args(["--schedule", "--start-window"])

    def test_force_needs_consume(self):
        with self.quiet_stderr():
            with self.assertRaises(SystemExit):
                codex_maint.parse_args(["--force"])


if __name__ == "__main__":
    unittest.main()
