"""Phase 2 AEST (:00/:15/:30/:45) marketing-mode scheduler & batched daily digest (zero failure-notice emails)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import STUDIO_ROOT, load_json, load_rules, now_aest_iso, save_json

AEST = timezone(timedelta(hours=10))


def validate_quarter_hour_time(time_hhmm: str) -> bool:
    """Enforce Markus's 29 Oct rule: every routine runs strictly on :00, :15, :30, or :45."""
    parts = time_hhmm.strip().split(":")
    if len(parts) != 2:
        return False
    hh, mm = int(parts[0]), int(parts[1])
    return 0 <= hh <= 23 and mm in (0, 15, 30, 45)


def validate_marketing_mode_schedule(rules: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    if rules is None:
        rules = load_rules()
    sched = rules.get("marketing_mode_schedules_aest", {})
    allowed_marks = set(sched.get("allowed_minute_marks", [0, 15, 30, 45]))
    issues: list[str] = []

    for job in sched.get("jobs", []):
        t = str(job.get("time", ""))
        parts = t.split(":")
        if len(parts) != 2 or int(parts[1]) not in allowed_marks:
            issues.append(f"Job '{job.get('bot')}:{job.get('name')}' time '{t}' is not on :00/:15/:30/:45.")
        # Marketing mode allows only Heimdall, Marketing (ex-Freya), and Tyr
        if job.get("bot") not in ("Heimdall", "Marketing", "Freya", "Tyr"):
            issues.append(f"Paused bot '{job.get('bot')}' has an active scheduled routine.")
    return len(issues) == 0, issues


def queue_failure_for_daily_digest(
    bot_name: str,
    job_name: str,
    error_message: str,
    studio_root: str | Path = STUDIO_ROOT,
) -> Path:
    """Record a failure ONLY for the bot's normal daily digest; NEVER send failure-notice emails."""
    q_path = Path(studio_root) / "logs" / "daily_digest_queue.json"
    if q_path.exists():
        data = load_json(q_path)
    else:
        data = {"pending_failures": []}
    data["pending_failures"].append(
        {
            "timestamp_aest": now_aest_iso(),
            "bot": bot_name,
            "job": job_name,
            "error": error_message,
            "email_sent": False,
        }
    )
    return save_json(q_path, data)


def build_heimdall_daily_list(
    studio_root: str | Path = STUDIO_ROOT,
    max_items: int = 5,
) -> dict[str, Any]:
    """Generate Heimdall's weekday 07:00 AEST list (<= 5 bullets, each with a recommendation)."""
    q_path = Path(studio_root) / "logs" / "daily_digest_queue.json"
    pending = load_json(q_path).get("pending_failures", []) if q_path.exists() else []

    items: list[dict[str, str]] = [
        {
            "item": "DA-04 / INC-20261008-001 (S1): Rotate exposed Hypest keys + enable passkeys/2FA",
            "recommendation": "Rotate Stripe live/webhook secrets first, then AWS/Google/Apple/DB, then turn on 2FA.",
        }
    ]
    for fail in pending[: max(0, max_items - len(items))]:
        items.append(
            {
                "item": f"{fail['bot']} job '{fail['job']}' failed at {fail['timestamp_aest']}",
                "recommendation": f"Inspect local log and re-run manually; error: {fail['error'][:120]}",
            }
        )

    return {
        "generated_at_aest": datetime.now(AEST).isoformat(timespec="seconds"),
        "bot": "Heimdall",
        "max_items": max_items,
        "items": items[:max_items],
    }
