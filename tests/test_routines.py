"""Routine runner (Phase 4.1): due times, catch-up, missed, once per day."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import routines  # noqa: E402

AEST = timezone(timedelta(hours=10))
JOBS = [{"bot": "Heimdall", "name": "brief", "days": ["mon", "tue", "wed", "thu", "fri"], "time": "07:00"},
        {"bot": "Marketing", "name": "plan", "days": ["fri"], "time": "07:00"},
        {"bot": "Tyr", "name": "nobody", "days": ["thu"], "time": "13:15"}]


class TestRoutines(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "runs.json"
        self.path.write_text('{"days": {}}', encoding="utf-8")   # an existing log
        self.calls = []
        self.runners = {"brief": lambda j: (self.calls.append(j["name"]) or ("done", "ok")),
                        "plan": lambda j: ("done", "ok")}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def at(self, s: str) -> datetime:
        return datetime.fromisoformat(s).replace(tzinfo=AEST)

    def test_runs_once_at_time_on_the_right_days(self) -> None:
        thu_659 = self.at("2026-11-26T06:59:00")
        self.assertEqual(routines.tick(thu_659, JOBS, self.path, self.runners), [])
        out = routines.tick(self.at("2026-11-26T07:00:30"), JOBS, self.path, self.runners)
        self.assertEqual(out, ["Heimdall:brief done"])
        self.assertEqual(routines.tick(self.at("2026-11-26T07:05:00"), JOBS, self.path, self.runners), [])
        self.assertEqual(self.calls, ["brief"])

    def test_catch_up_then_missed(self) -> None:
        out = routines.tick(self.at("2026-11-26T08:30:00"), JOBS, self.path, self.runners)
        self.assertEqual(out, ["Heimdall:brief done"])
        out = routines.tick(self.at("2026-11-26T14:00:00"), JOBS, self.path, self.runners)
        self.assertEqual(out, ["Tyr:nobody skipped"])
        out = routines.tick(self.at("2026-11-27T11:00:00"), JOBS, self.path, self.runners)
        self.assertEqual(sorted(out), ["Heimdall:brief missed", "Marketing:plan missed"])
        self.assertEqual(routines.load_runs(self.path)["2026-11-27"]["Heimdall:brief"]["status"], "missed")

    def test_failure_is_recorded(self) -> None:
        bad = {"brief": lambda j: 1 / 0}
        out = routines.tick(self.at("2026-11-26T07:01:00"), JOBS, self.path, bad)
        self.assertEqual(out, ["Heimdall:brief failed"])
        self.assertIn("ZeroDivisionError", routines.load_runs(self.path)["2026-11-26"]["Heimdall:brief"]["note"])

    def test_first_start_never_claims_missed(self) -> None:
        self.path.unlink()
        out = routines.tick(self.at("2026-11-26T17:55:00"), JOBS, self.path, self.runners)
        self.assertEqual(sorted(out), ["Heimdall:brief not_tracked", "Tyr:nobody not_tracked"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
