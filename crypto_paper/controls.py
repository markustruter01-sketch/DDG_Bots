"""Markus's buttons for the paper accounts.

The dashboard drops a small command file into data/crypto/inbox/; the bot picks it up within a few seconds,
carries it out and files it under inbox/done/. Nothing is deleted: a reset archives the old account first.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

ACTIONS = ("pause", "resume", "close_trades", "reset", "decide_now")
ACCOUNTS = ("qwen", "journal", "trend", "flip", "all")
MAX_AGE_S = 120          # a command older than this (bot was off) is ignored, never carried out late


def send(data: Path, action: str, account: str) -> Dict[str, Any]:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action '{action}'.")
    if account not in ACCOUNTS:
        raise ValueError(f"Unknown account '{account}'.")
    cmd = {"id": uuid.uuid4().hex[:10], "action": action, "account": "all" if action == "decide_now" else account,
           "at": time.time()}
    box = data / "inbox"
    box.mkdir(parents=True, exist_ok=True)
    tmp = box / f"{time.time_ns()}_{cmd['id']}.tmp"
    tmp.write_text(json.dumps(cmd), encoding="utf-8")
    os.replace(tmp, tmp.with_suffix(".json"))
    return cmd


def pending(data: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    out = []
    for f in sorted((data / "inbox").glob("*.json")):
        try:
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            out.append((f, {}))
    return out


def file_done(path: Path) -> None:
    done = path.parent / "done"
    done.mkdir(exist_ok=True)
    os.replace(path, done / path.name)
