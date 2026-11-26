"""Routine runner (plan Phase 4.1, 26 Nov 2026).

Runs every routine listed in config/rules.json -> marketing_mode_schedules_aest.jobs,
once per day at its time. If the PC or studio was off at that time, the routine
still runs if the studio comes back within CATCH_UP_HOURS; otherwise it is
recorded as missed. Every outcome is written to logs/routine_runs.json.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CATCH_UP_HOURS = 2
KEEP_DAYS = 14
_LOCK = threading.Lock()


def _key(job: Dict[str, Any]) -> str:
    return f"{job['bot']}:{job['name']}"


def load_runs(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("days", {})
    except Exception:
        return {}


def record(path: Path, day: str, job: Dict[str, Any], status: str, note: str, at: str) -> None:
    with _LOCK:
        days = load_runs(path)
        days.setdefault(day, {})[_key(job)] = {"status": status, "note": note[:300], "at": at}
        for old in sorted(days)[:-KEEP_DAYS]:
            days.pop(old, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"days": days}, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def due(now: datetime, jobs: List[Dict[str, Any]], runs: Dict[str, Dict[str, Any]]) -> List[tuple[Dict[str, Any], str]]:
    """(job, 'run'|'missed') for every job scheduled today that has no record yet and whose time has come."""
    day = now.strftime("%Y-%m-%d")
    done = runs.get(day, {})
    out = []
    for job in jobs:
        if DAYS[now.weekday()] not in [d.lower()[:3] for d in job.get("days", [])]:
            continue
        if _key(job) in done:
            continue
        hh, mm = (int(x) for x in str(job.get("time", "00:00")).split(":"))
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < start:
            continue
        out.append((job, "run" if now - start <= timedelta(hours=CATCH_UP_HOURS) else "missed"))
    return out


def tick(now: datetime, jobs: List[Dict[str, Any]], runs_path: Path,
         runners: Dict[str, Callable[[Dict[str, Any]], tuple[str, str]]]) -> List[str]:
    """Run or mark everything due. A runner returns (status, note): done | skipped | failed."""
    day, at = now.strftime("%Y-%m-%d"), now.isoformat(timespec="seconds")
    first_start = not runs_path.exists()
    results = []
    for job, what in due(now, jobs, load_runs(runs_path)):
        if first_start:   # no record of what happened before this log existed: say so, never guess "missed"
            record(runs_path, day, job, "not_tracked", "Before the routine log started.", at)
            results.append(f"{_key(job)} not_tracked")
            continue
        if what == "missed":
            record(runs_path, day, job, "missed", f"Studio was not running at {job['time']} (more than {CATCH_UP_HOURS} h ago).", at)
            results.append(f"{_key(job)} missed")
            continue
        fn = runners.get(job["name"])
        if fn is None:
            record(runs_path, day, job, "skipped", "No runner exists for this routine yet.", at)
            results.append(f"{_key(job)} skipped")
            continue
        record(runs_path, day, job, "running", "", at)
        try:
            status, note = fn(job)
        except Exception as exc:
            status, note = "failed", f"{type(exc).__name__}: {exc}"
        record(runs_path, day, job, status, note, at)
        results.append(f"{_key(job)} {status}")
    return results
