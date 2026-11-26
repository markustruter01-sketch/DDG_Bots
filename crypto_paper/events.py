"""Scheduled announcements (config/crypto_events.json) and the blackout around them.

The blackout only ever stops NEW trades. Open trades keep their stop and target. It is off unless an account's
settings say `blackout` (rules.EVENT_BLACKOUT), and exists so the replay rig can measure whether it helps.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from . import rules as R

EVENTS_FILE = Path(__file__).resolve().parent.parent / "config" / "crypto_events.json"


def load(path: Path = EVENTS_FILE) -> List[Tuple[datetime, str]]:
    """[(time in UTC, what)], oldest first. A missing or broken file means no events (and so no blackout)."""
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8")).get("events", [])
        out = [(datetime.strptime(r["utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc), str(r.get("what", "event")))
               for r in rows]
        return sorted(out)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def in_blackout(now: datetime, events: List[Tuple[datetime, str]], before_min: int = R.BLACKOUT_MINUTES_BEFORE,
                after_min: int = R.BLACKOUT_MINUTES_AFTER) -> Optional[str]:
    """The announcement `now` is too close to, or None."""
    for when, what in events:
        if when - timedelta(minutes=before_min) <= now <= when + timedelta(minutes=after_min):
            return what
    return None
