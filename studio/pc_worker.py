"""PC worker: look around, then tidy up with plan -> approve -> undo (plan Phase 2).

Plain code only. The AI may suggest a plan, but every check and every file move
happens here, and only after Markus approves it in the dashboard.

- Looking tools (read only): list a folder, folder sizes, search, find duplicates.
- Plans: a list of moves. Each move goes to a new place, or to "QUARANTINE".
  There is no delete. Nothing is ever overwritten.
- Dry run on creation: every move is checked (allowed place? exists? target free?
  inside a code repo? changed recently?) and the plan shows totals and warnings.
- Approve: the checks run again, then moves happen one by one, each written to
  the plan's journal as it completes. A failure stops the batch; what already
  moved stays recorded.
- Undo: the journal is played backwards. A move is skipped (and reported) if
  something now sits in its original place.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from studio import governance

PLANS_FILE = governance.STUDIO_ROOT / "data" / "pc_plans.json"
QUARANTINE = "QUARANTINE"

MAX_MOVES = 2000                 # per plan
MAX_PLAN_BYTES = 200 * 10**9     # 200 GB per plan
MAX_LIST = 500                   # entries returned by a look
MAX_SCAN_FILES = 50000           # files walked by sizes/search/duplicates
RECENT_DAYS = governance.RECENT_DAYS

_LOCK = threading.Lock()


class WorkerError(ValueError):
    pass


def _allowed(p: Path) -> Path:
    ok, msg = governance.is_path_safe_and_allowed(p)
    if not ok:
        raise WorkerError(f"{p}: {msg}")
    return p


def _walk(root: Path) -> Iterable[Path]:
    """Files under root, skipping blocked places, at most MAX_SCAN_FILES."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not governance.blocked_reason(Path(dirpath) / d)]
        for f in filenames:
            p = Path(dirpath) / f
            if governance.blocked_reason(p):
                continue
            yield p
            n += 1
            if n >= MAX_SCAN_FILES:
                return


def _stat(p: Path) -> Optional[os.stat_result]:
    try:
        return p.stat()
    except OSError:
        return None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, governance.AEST).isoformat(timespec="minutes")


# ── looking (read only) ─────────────────────────────────────────────────────
def list_dir(path: str) -> Dict[str, Any]:
    root = _allowed(Path(path))
    if not root.is_dir():
        raise WorkerError(f"{root} is not a folder.")
    items = []
    for child in sorted(root.iterdir(), key=lambda c: c.name.lower()):
        if len(items) >= MAX_LIST:
            break
        st = _stat(child)
        items.append({"name": child.name, "path": str(child), "is_dir": child.is_dir(),
                      "size": st.st_size if st and not child.is_dir() else None,
                      "modified": _iso(st.st_mtime) if st else None,
                      "blocked": governance.blocked_reason(child)})
    return {"path": str(root), "items": items, "truncated": len(items) >= MAX_LIST}


def folder_sizes(path: str) -> Dict[str, Any]:
    """Size of each item directly inside a folder, biggest first."""
    root = _allowed(Path(path))
    rows = []
    for child in root.iterdir():
        if governance.blocked_reason(child):
            rows.append({"name": child.name, "path": str(child), "size": None, "files": None, "blocked": governance.blocked_reason(child)})
            continue
        if child.is_dir():
            size = files = 0
            for f in _walk(child):
                st = _stat(f)
                if st:
                    size += st.st_size
                    files += 1
        else:
            st = _stat(child)
            size, files = (st.st_size if st else 0), 1
        rows.append({"name": child.name, "path": str(child), "size": size, "files": files, "blocked": None})
    rows.sort(key=lambda r: r["size"] or 0, reverse=True)
    return {"path": str(root), "items": rows[:MAX_LIST]}


def search(path: str, name: str = "*", older_than_days: Optional[float] = None,
           min_size_mb: Optional[float] = None) -> Dict[str, Any]:
    root = _allowed(Path(path))
    pattern = (name or "*").lower()
    cutoff = time.time() - older_than_days * 86400 if older_than_days else None
    min_bytes = min_size_mb * 1e6 if min_size_mb else None
    hits = []
    for f in _walk(root):
        if not fnmatch.fnmatch(f.name.lower(), pattern):
            continue
        st = _stat(f)
        if not st or (cutoff and st.st_mtime > cutoff) or (min_bytes and st.st_size < min_bytes):
            continue
        hits.append({"path": str(f), "size": st.st_size, "modified": _iso(st.st_mtime)})
        if len(hits) >= MAX_LIST:
            break
    return {"path": str(root), "items": hits, "truncated": len(hits) >= MAX_LIST}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def find_duplicates(path: str, min_size_mb: float = 1.0) -> Dict[str, Any]:
    """Files with identical content (same size, then same SHA-256)."""
    root = _allowed(Path(path))
    by_size: Dict[int, List[Path]] = {}
    for f in _walk(root):
        st = _stat(f)
        if st and st.st_size >= min_size_mb * 1e6:
            by_size.setdefault(st.st_size, []).append(f)
    groups = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        by_hash: Dict[str, List[str]] = {}
        for f in files:
            try:
                by_hash.setdefault(_sha256(f), []).append(str(f))
            except OSError:
                continue
        for paths in by_hash.values():
            if len(paths) > 1:
                groups.append({"size": size, "copies": sorted(paths), "wasted": size * (len(paths) - 1)})
    groups.sort(key=lambda g: g["wasted"], reverse=True)
    return {"path": str(root), "groups": groups[:200], "wasted_total": sum(g["wasted"] for g in groups)}


# ── plans ───────────────────────────────────────────────────────────────────
def _load() -> List[Dict[str, Any]]:
    if not PLANS_FILE.exists():
        return []
    try:
        return json.loads(PLANS_FILE.read_text(encoding="utf-8")).get("plans", [])
    except Exception:
        return []


def _save(plans: List[Dict[str, Any]]) -> None:
    PLANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PLANS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"plans": plans, "updated_at_aest": governance.now_aest_iso()}, indent=2), encoding="utf-8")
    os.replace(tmp, PLANS_FILE)


def _size_of(p: Path) -> tuple[int, int, float]:
    """(bytes, files, newest mtime)."""
    if p.is_dir():
        size = files = 0
        newest = _stat(p).st_mtime if _stat(p) else 0
        for f in _walk(p):
            st = _stat(f)
            if st:
                size += st.st_size
                files += 1
                newest = max(newest, st.st_mtime)
        return size, files, newest
    st = _stat(p)
    return (st.st_size, 1, st.st_mtime) if st else (0, 0, 0)


def _in_repo(p: Path) -> bool:
    return any((q / ".git").exists() for q in [p, *p.parents])


def _check_move(src: str, dest: str) -> Dict[str, Any]:
    """One move, checked. status: ok | warn | blocked."""
    row: Dict[str, Any] = {"src": src, "dest": dest, "status": "ok", "notes": [], "size": 0, "files": 0}
    s = Path(src)
    ok, msg = governance.is_path_safe_and_allowed(s)
    if not ok:
        return {**row, "status": "blocked", "notes": [msg]}
    if not s.exists():
        return {**row, "status": "blocked", "notes": ["not found"]}
    if dest != QUARANTINE:
        d = Path(dest)
        ok, msg = governance.is_path_safe_and_allowed(d)
        if not ok:
            return {**row, "status": "blocked", "notes": [f"destination: {msg}"]}
        if d.exists():
            return {**row, "status": "blocked", "notes": ["destination already exists (nothing is ever overwritten)"]}
        if governance._under(governance._norm(d), governance._norm(s)):
            return {**row, "status": "blocked", "notes": ["cannot move a folder inside itself"]}
    size, files, newest = _size_of(s)
    row.update(size=size, files=files, is_dir=s.is_dir())
    if (time.time() - newest) / 86400 < RECENT_DAYS:
        row["notes"].append(f"changed in the last {RECENT_DAYS} days")
    if _in_repo(s):
        row["notes"].append("inside a code repo")
    if row["notes"]:
        row["status"] = "warn"
    return row


def create_plan(proposer: str, title: str, moves: List[Dict[str, str]], reason: str = "") -> Dict[str, Any]:
    if not moves:
        raise WorkerError("A plan needs at least one move.")
    if len(moves) > MAX_MOVES:
        raise WorkerError(f"Too many moves ({len(moves)}); the limit is {MAX_MOVES} per plan.")
    seen_src, seen_dest = set(), set()
    rows = []
    for m in moves:
        src, dest = str(m.get("src", "")).strip(), str(m.get("dest", "")).strip()
        if not src or not dest:
            raise WorkerError("Every move needs a 'src' and a 'dest' (a path, or QUARANTINE).")
        row = _check_move(src, dest)
        ks, kd = governance._norm(src), governance._norm(dest)
        if ks in seen_src or (dest != QUARANTINE and kd in seen_dest):
            row.update(status="blocked", notes=row["notes"] + ["appears twice in this plan"])
        seen_src.add(ks)
        if dest != QUARANTINE:
            seen_dest.add(kd)
        rows.append(row)
    total = sum(r["size"] for r in rows if r["status"] != "blocked")
    if total > MAX_PLAN_BYTES:
        raise WorkerError(f"Plan moves {total / 1e9:.1f} GB; the limit is {MAX_PLAN_BYTES / 1e9:.0f} GB. Split it.")
    plan = {
        "id": "plan-" + uuid.uuid4().hex[:10],
        "proposer": proposer,
        "title": title or "Tidy-up plan",
        "reason": reason,
        "created_at_aest": governance.now_aest_iso(),
        "status": "pending_markus_approval",
        "moves": rows,
        "summary": {
            "moves": len(rows),
            "will_move": sum(1 for r in rows if r["status"] != "blocked"),
            "blocked": sum(1 for r in rows if r["status"] == "blocked"),
            "warnings": sum(1 for r in rows if r["status"] == "warn"),
            "files": sum(r["files"] for r in rows if r["status"] != "blocked"),
            "bytes": total,
            "to_quarantine": sum(1 for r in rows if r["dest"] == QUARANTINE and r["status"] != "blocked"),
        },
        "journal": [],
        "note": None,
    }
    with _LOCK:
        plans = _load()
        plans.append(plan)
        _save(plans)
    return plan


def list_plans() -> List[Dict[str, Any]]:
    return _load()


def _find(plans: List[Dict[str, Any]], plan_id: str) -> Dict[str, Any]:
    plan = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        raise WorkerError(f"Plan {plan_id} not found.")
    return plan


def reject_plan(plan_id: str) -> Dict[str, Any]:
    with _LOCK:
        plans = _load()
        plan = _find(plans, plan_id)
        if plan["status"] != "pending_markus_approval":
            raise WorkerError(f"Plan is already '{plan['status']}'.")
        plan.update(status="rejected", note="Rejected by Markus. Nothing moved.", resolved_at_aest=governance.now_aest_iso())
        _save(plans)
        return plan


def approve_plan(plan_id: str) -> Dict[str, Any]:
    with _LOCK:
        plans = _load()
        plan = _find(plans, plan_id)
        if plan["status"] != "pending_markus_approval":
            raise WorkerError(f"Plan is already '{plan['status']}'.")
        plan.update(status="running", approved_at_aest=governance.now_aest_iso())
        _save(plans)
        qdir = governance.QUARANTINE_ROOT / datetime.now(governance.AEST).strftime("%Y-%m-%d") / plan_id
        done = failed = skipped = 0
        for row in plan["moves"]:
            if row["status"] == "blocked":
                skipped += 1
                continue
            fresh = _check_move(row["src"], row["dest"])      # re-check now: things change
            if fresh["status"] == "blocked":
                row.update(result="skipped", result_note="; ".join(fresh["notes"]))
                skipped += 1
                continue
            src = Path(row["src"])
            dest = qdir / f"{done:04d}_{src.name}" if row["dest"] == QUARANTINE else Path(row["dest"])
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
            except Exception as exc:
                row.update(result="failed", result_note=str(exc))
                failed += 1
                break
            plan["journal"].append({"src": str(src), "dest": str(dest), "at": governance.now_aest_iso()})
            row.update(result="moved", moved_to=str(dest))
            done += 1
            _save(plans)                                         # journal is on disk after every move
        if plan["journal"] and row_quarantined(plan):
            qdir.mkdir(parents=True, exist_ok=True)
            (qdir / "manifest.json").write_text(json.dumps({"plan_id": plan_id, "title": plan["title"],
                                                            "journal": plan["journal"]}, indent=2), encoding="utf-8")
        plan["status"] = "done" if not failed else "stopped"
        plan["note"] = f"Moved {done}, skipped {skipped}" + (f", stopped after a failure" if failed else "") + ". Undo is available."
        plan["finished_at_aest"] = governance.now_aest_iso()
        _save(plans)
        return plan


def row_quarantined(plan: Dict[str, Any]) -> bool:
    return any(r.get("dest") == QUARANTINE and r.get("result") == "moved" for r in plan["moves"])


def undo_plan(plan_id: str) -> Dict[str, Any]:
    with _LOCK:
        plans = _load()
        plan = _find(plans, plan_id)
        if plan["status"] not in ("done", "stopped", "partly_undone"):
            raise WorkerError(f"Plan is '{plan['status']}'; only a run plan can be undone.")
        restored = kept = 0
        remaining = []
        for step in reversed(plan["journal"]):
            src, dest = Path(step["src"]), Path(step["dest"])
            if src.exists() or not dest.exists():
                step["undo_note"] = "skipped: original place is taken" if src.exists() else "skipped: moved copy is missing"
                remaining.append(step)
                kept += 1
                continue
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(src))
                restored += 1
            except Exception as exc:
                step["undo_note"] = f"failed: {exc}"
                remaining.append(step)
                kept += 1
        plan["journal"] = list(reversed(remaining))
        plan["status"] = "undone" if not kept else "partly_undone"
        plan["note"] = f"Undo: put back {restored}" + (f", {kept} could not be put back (see journal)" if kept else "") + "."
        plan["undone_at_aest"] = governance.now_aest_iso()
        _save(plans)
        return plan
