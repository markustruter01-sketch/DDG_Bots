"""Calibrated time estimation, job time log, feedback log, and delivery scorecard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import STUDIO_ROOT, load_json, now_aest_iso, save_json


def _logs_dir(studio_root: str | Path = STUDIO_ROOT) -> Path:
    d = Path(studio_root) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def predict_minutes(
    gut_minutes: float,
    studio_root: str | Path = STUDIO_ROOT,
) -> dict[str, float]:
    """Calibrate gut time estimate against estimate_history.json before quoting Markus."""
    hist_path = _logs_dir(studio_root) / "estimate_history.json"
    ratios: list[float] = []
    if hist_path.exists():
        data = load_json(hist_path)
        for row in data.get("entries", []):
            g = float(row.get("gut_minutes", 0.0))
            a = float(row.get("actual_minutes", 0.0))
            if g > 0 and a > 0:
                ratios.append(a / g)

    if not ratios:
        factor = 1.25
        spread = 0.25
    else:
        factor = sum(ratios) / len(ratios)
        diffs = [abs(r - factor) for r in ratios]
        spread = max(0.15, sum(diffs) / len(diffs))

    pred = round(gut_minutes * factor, 1)
    low = round(max(1.0, gut_minutes * max(0.5, factor - spread)), 1)
    high = round(gut_minutes * (factor + spread), 1)
    return {
        "gut_minutes": round(gut_minutes, 1),
        "predicted_minutes": pred,
        "range_low_minutes": low,
        "range_high_minutes": high,
        "calibration_factor": round(factor, 3),
        "sample_count": len(ratios),
    }


def log_job_time(
    job_name: str,
    gut_minutes: float,
    actual_minutes: float,
    studio_root: str | Path = STUDIO_ROOT,
    allowed_roots: list[str | Path] | None = None,
) -> Path:
    """Append real AEST start/actual vs estimate to estimate_history.json and job_time_log.md."""
    logs = _logs_dir(studio_root)
    hist_path = logs / "estimate_history.json"
    if hist_path.exists():
        data = load_json(hist_path)
    else:
        data = {"entries": []}

    ts = now_aest_iso()
    data["entries"].append(
        {
            "timestamp_aest": ts,
            "job": job_name,
            "gut_minutes": round(gut_minutes, 2),
            "actual_minutes": round(actual_minutes, 2),
        }
    )
    save_json(hist_path, data, allowed_roots=allowed_roots)

    md_path = logs / "job_time_log.md"
    if not md_path.exists():
        md_path.write_text(
            "# DDG Job Time Log (AEST)\n\n| Timestamp (AEST) | Job | Gut (min) | Actual (min) |\n| :--- | :--- | ---: | ---: |\n",
            encoding="utf-8",
        )
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(f"| {ts} | {job_name} | {gut_minutes:.1f} | {actual_minutes:.1f} |\n")
    return md_path


def log_feedback(
    rule_summary: str,
    reason: str,
    gate_id: str = "",
    studio_root: str | Path = STUDIO_ROOT,
) -> Path:
    """Record Markus's edit feedback with its automated gate reference."""
    md_path = _logs_dir(studio_root) / "feedback_log.md"
    if not md_path.exists():
        md_path.write_text("# DDG Video Feedback Log\n\n", encoding="utf-8")
    with open(md_path, "a", encoding="utf-8") as f:
        gate_str = f" [`{gate_id}`]" if gate_id else ""
        f.write(f"- **{now_aest_iso()}**{gate_str}: {rule_summary} — *Reason:* {reason}\n")
    return md_path


def update_scorecard(
    job_id: str,
    fix_requests: int,
    repeated_mistakes: list[str] | None = None,
    notes: str = "",
    studio_root: str | Path = STUDIO_ROOT,
) -> Path:
    """Track fix requests per delivery (target trending to zero)."""
    md_path = _logs_dir(studio_root) / "scorecard.md"
    if not md_path.exists():
        md_path.write_text(
            "# DDG Edit Scorecard\n\n| Timestamp (AEST) | Job | Fix Requests | Repeated Mistakes | Notes |\n| :--- | :--- | ---: | :--- | :--- |\n",
            encoding="utf-8",
        )
    rep = ", ".join(repeated_mistakes or []) or "None"
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(f"| {now_aest_iso()} | {job_id} | {fix_requests} | {rep} | {notes} |\n")
    return md_path
