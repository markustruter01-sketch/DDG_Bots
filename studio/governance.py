"""Access control and safe "delete" for DDG Local Bot Studio.

Rules (plan Phase 1, 26 Nov 2026):
- An always-blocked list applies whatever the scope, "full_system" included:
  Windows and program folders, AppData, key and credential folders, .git folders,
  backups, the AI models, the marketing browser profile, the quarantine and the
  studio itself. Nothing on it can be proposed for removal.
- Nothing is ever really deleted. An approved proposal MOVES the item into the
  quarantine (F:\\DDG_Quarantine\\<date>\\<proposal id>\\) with a manifest, and
  it can be restored to where it was.
- Proposals carry real checks (size, file count, last changed, inside a code
  repo) instead of invented bot votes.
- Only Markus approves, from the dashboard (the server refuses requests that do
  not come from the dashboard).
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

AEST = timezone(timedelta(hours=10))
STUDIO_ROOT = Path(__file__).resolve().parent.parent

PERMISSIONS_FILE = STUDIO_ROOT / "data" / "computer_permissions.json"
PROPOSALS_FILE = STUDIO_ROOT / "data" / "governance_proposals.json"
QUARANTINE_ROOT = Path(os.environ.get("DDG_QUARANTINE_ROOT", "F:/DDG_Quarantine"))

SCOPES = ("ddg_workspace", "full_f_drive", "desktop_and_f", "unrestricted_user", "full_system", "custom")
DEFAULT_SCOPE = "ddg_workspace"

RECENT_DAYS = 7          # changed within this many days -> warning
MAX_WALK_FILES = 20000   # stop counting after this many files (size shown as "at least")

_LOCK = threading.Lock()


def now_aest_iso() -> str:
    return datetime.now(AEST).isoformat(timespec="seconds")


# ── paths ────────────────────────────────────────────────────────────────────
def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))


def _norm(p: Path | str) -> str:
    """Resolved, forward-slash, lower-case form (Windows paths are case-insensitive)."""
    try:
        r = Path(p).resolve()
    except Exception:
        r = Path(p)
    return str(r).replace("\\", "/").rstrip("/").lower()


def _under(child: str, root: str) -> bool:
    return child == root or child.startswith(root + "/")


def blocked_places() -> List[tuple[str, str]]:
    """(normalised path, why) for every always-blocked place."""
    home = _home()
    places: list[tuple[Path, str]] = [
        (Path("C:/Windows"), "Windows system folder"),
        (Path("C:/Program Files"), "installed programs"),
        (Path("C:/Program Files (x86)"), "installed programs"),
        (Path("C:/ProgramData"), "program data"),
        (Path("C:/$Recycle.Bin"), "Recycle Bin"),
        (Path("F:/$RECYCLE.BIN"), "Recycle Bin"),
        (Path("C:/System Volume Information"), "Windows system data"),
        (Path("F:/System Volume Information"), "Windows system data"),
        (Path("F:/Backups"), "backups"),
        (Path("F:/DDG_Video_Studio/models"), "the AI models"),
        (Path("F:/DDG_Video_Studio/marketing_browser_profile"), "the marketing browser sign-ins"),
        (QUARANTINE_ROOT, "the quarantine (use Restore instead)"),
        (STUDIO_ROOT, "the Bot Studio itself"),
        (home / "AppData", "app data and browser profiles"),
    ]
    for name in (".ssh", ".gnupg", ".aws", ".azure", ".config", ".docker", ".kube",
                 ".ollama", ".gemini", ".grokbot", ".codex", ".vscode", ".vscode-shared"):
        places.append((home / name, "keys, credentials or tool settings"))
    return [(_norm(p), why) for p, why in places]


SECRET_NAMES = (".env", "id_rsa", "id_ed25519", "id_ecdsa", "credentials", "credentials.json")
SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".kdbx")


def blocked_reason(target: Path | str) -> Optional[str]:
    """Why this path can never be touched, or None."""
    n = _norm(target)
    parts = n.split("/")
    if len(parts) <= 2 and (len(parts) == 1 or parts[1] == ""):
        return "a whole drive"
    if n in (_norm(_home()), _norm(_home().parent)):
        return "your whole user folder"
    if ".git" in parts:
        return "inside a .git folder (code history)"
    for root, why in blocked_places():
        if _under(n, root):
            return why
        if _under(root, n):
            return f"it contains {why}"
    name = parts[-1]
    if name in SECRET_NAMES or name.startswith(("id_rsa", "id_ed25519")) or name.endswith(SECRET_SUFFIXES):
        return "a key or credentials file"
    return None


# ── permissions (the scope dropdown) ────────────────────────────────────────
def load_permissions() -> Dict[str, Any]:
    if not PERMISSIONS_FILE.exists():
        doc = {"scope": DEFAULT_SCOPE, "custom_paths": [], "updated_at_aest": now_aest_iso()}
        save_permissions(doc)
        return doc
    try:
        doc = json.loads(PERMISSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        doc = {"scope": DEFAULT_SCOPE, "custom_paths": []}
    if doc.get("scope") not in SCOPES:
        doc["scope"] = DEFAULT_SCOPE
    doc.setdefault("custom_paths", [])
    return doc


def save_permissions(perms: Dict[str, Any]) -> Dict[str, Any]:
    scope = str(perms.get("scope", DEFAULT_SCOPE))
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope '{scope}'. Use one of: {', '.join(SCOPES)}.")
    custom = [str(p) for p in perms.get("custom_paths", []) if str(p).strip()]
    doc = {"scope": scope, "custom_paths": custom, "updated_at_aest": now_aest_iso()}
    PERMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERMISSIONS_FILE.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def get_allowed_roots() -> List[Path]:
    scope = load_permissions()["scope"]
    home = _home()
    ddg = home / "Desktop" / "DDG"
    if scope == "ddg_workspace":
        return [ddg, Path("F:/DDG_Video_Studio")]
    if scope == "full_f_drive":
        return [ddg, Path("F:/")]
    if scope == "desktop_and_f":
        return [home / "Desktop", home / "Downloads", Path("F:/")]
    if scope == "unrestricted_user":
        roots = [home, Path("F:/")]
        roots += [Path(d) for d in ("D:/", "E:/") if Path(d).exists()]
        return roots
    if scope == "full_system":
        return [Path("C:/"), Path("F:/")]
    custom = [Path(p) for p in load_permissions().get("custom_paths", []) if Path(p).exists()]
    return custom or [ddg]


def is_path_safe_and_allowed(target: Path | str) -> tuple[bool, str]:
    why = blocked_reason(target)
    if why:
        return False, f"Always blocked: {why}."
    n = _norm(target)
    for root in get_allowed_roots():
        if _under(n, _norm(root)):
            return True, "Allowed"
    scope = load_permissions()["scope"]
    return False, f"Outside the current access setting ('{scope}'). Change it in Settings to allow this place."


# ── real checks (replace the old invented votes) ────────────────────────────
def run_checks(target: Path) -> Dict[str, Any]:
    p = Path(target)
    size = files = 0
    newest = p.stat().st_mtime
    capped = False
    if p.is_dir():
        for root, dirs, fs in os.walk(p):
            for f in fs:
                try:
                    st = (Path(root) / f).stat()
                except OSError:
                    continue
                size += st.st_size
                files += 1
                newest = max(newest, st.st_mtime)
                if files >= MAX_WALK_FILES:
                    capped = True
                    break
            if capped:
                break
    else:
        size, files = p.stat().st_size, 1
    in_repo = any((q / ".git").exists() for q in [p, *p.parents]) if p.exists() else False
    age_days = (time.time() - newest) / 86400
    checks = [
        {"name": "Size", "ok": True, "detail": f"{'at least ' if capped else ''}{size / 1e9:.2f} GB in {files}{'+' if capped else ''} files"},
        {"name": "Last changed", "ok": age_days >= RECENT_DAYS,
         "detail": f"{age_days:.0f} days ago" + ("" if age_days >= RECENT_DAYS else f" (within {RECENT_DAYS} days: still in use?)")},
        {"name": "Code repo", "ok": not in_repo, "detail": "inside a code repo: check it is pushed" if in_repo else "not in a code repo"},
        {"name": "Blocked list", "ok": True, "detail": "not on the always-blocked list"},
    ]
    return {"checks": checks, "size_bytes": size, "file_count": files, "warnings": sum(1 for c in checks if not c["ok"])}


# ── proposals ───────────────────────────────────────────────────────────────
def _load_proposals() -> List[Dict[str, Any]]:
    if not PROPOSALS_FILE.exists():
        return []
    try:
        return json.loads(PROPOSALS_FILE.read_text(encoding="utf-8")).get("proposals", [])
    except Exception:
        return []


def _save_proposals(proposals: List[Dict[str, Any]]) -> None:
    PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROPOSALS_FILE.write_text(json.dumps({"proposals": proposals, "updated_at_aest": now_aest_iso()}, indent=2),
                              encoding="utf-8")


def create_deletion_proposal(bot_name: str, target_path: str, reason: str,
                             active_bot_roster: Optional[List[str]] = None) -> Dict[str, Any]:
    """A request to move something into quarantine. active_bot_roster is kept for old callers."""
    p = Path(target_path)
    ok, msg = is_path_safe_and_allowed(p)
    if not ok:
        raise PermissionError(msg)
    if not p.exists():
        raise FileNotFoundError(f"'{target_path}' does not exist.")
    found = run_checks(p)
    proposal = {
        "id": "prop-" + uuid.uuid4().hex[:10],
        "proposer": bot_name,
        "action": "quarantine",
        "target": str(p.resolve()),
        "is_dir": p.is_dir(),
        "reason": reason,
        "status": "pending_markus_approval",
        "created_at_aest": now_aest_iso(),
        **found,
        "markus_decision": None,
        "execution_note": None,
        "quarantine_path": None,
    }
    with _LOCK:
        proposals = _load_proposals()
        proposals.append(proposal)
        _save_proposals(proposals)
    return proposal


def list_proposals(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    props = _load_proposals()
    return [p for p in props if p.get("status") == status_filter] if status_filter else props


def _quarantine_dir(prop_id: str) -> Path:
    return QUARANTINE_ROOT / datetime.now(AEST).strftime("%Y-%m-%d") / prop_id


def markus_resolve_proposal(proposal_id: str, decision: str, note: str = "") -> Dict[str, Any]:
    decision = decision.lower().strip()
    if decision not in ("approve", "execute", "veto", "reject"):
        raise ValueError(f"Invalid decision '{decision}'. Use 'approve' or 'veto'.")
    with _LOCK:
        proposals = _load_proposals()
        prop = next((p for p in proposals if p["id"] == proposal_id), None)
        if not prop:
            raise ValueError(f"Proposal {proposal_id} not found.")
        if prop["status"] != "pending_markus_approval":
            raise ValueError(f"Proposal {proposal_id} is already '{prop['status']}'.")
        prop["resolved_at_aest"] = now_aest_iso()
        if decision in ("veto", "reject"):
            prop.update(markus_decision="vetoed", status="vetoed", execution_note=note or "Vetoed by Markus. Nothing moved.")
            _save_proposals(proposals)
            return prop

        target = Path(prop["target"])
        ok, msg = is_path_safe_and_allowed(target)   # re-check: things may have changed since the proposal
        if not ok:
            prop.update(status="failed", execution_note=f"Refused at approval: {msg}")
        elif not target.exists():
            prop.update(markus_decision="approved", status="failed", execution_note=f"Nothing at {target} any more.")
        else:
            qdir = _quarantine_dir(proposal_id)
            try:
                qdir.mkdir(parents=True, exist_ok=False)
                dest = qdir / target.name
                manifest = {"proposal_id": proposal_id, "original_path": str(target), "moved_at_aest": now_aest_iso(),
                            "reason": prop.get("reason"), "proposer": prop.get("proposer"),
                            "size_bytes": prop.get("size_bytes"), "file_count": prop.get("file_count")}
                (qdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                shutil.move(str(target), str(dest))
                prop.update(markus_decision="approved", status="quarantined", quarantine_path=str(dest),
                            execution_note=f"Moved to quarantine: {dest}. Use Restore to put it back.")
            except Exception as exc:
                prop.update(markus_decision="approved", status="error",
                            execution_note=f"Move failed, original left in place if it still exists: {exc}")
        _save_proposals(proposals)
        return prop


def restore_proposal(proposal_id: str) -> Dict[str, Any]:
    with _LOCK:
        proposals = _load_proposals()
        prop = next((p for p in proposals if p["id"] == proposal_id), None)
        if not prop:
            raise ValueError(f"Proposal {proposal_id} not found.")
        if prop.get("status") != "quarantined" or not prop.get("quarantine_path"):
            raise ValueError(f"Proposal {proposal_id} is '{prop.get('status')}', not in quarantine.")
        src, original = Path(prop["quarantine_path"]), Path(prop["target"])
        if not src.exists():
            raise FileNotFoundError(f"The quarantined copy is missing: {src}")
        if original.exists():
            raise FileExistsError(f"Something is already at {original}. Move it first, then restore.")
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(original))
        prop.update(status="restored", restored_at_aest=now_aest_iso(), execution_note=f"Restored to {original}.")
        _save_proposals(proposals)
        return prop
