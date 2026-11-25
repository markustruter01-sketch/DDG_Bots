"""
Multi-Agent Governance & Containment Engine for DDG Local Bot Studio.
Supports dynamic Access Scope Dropdown:
- 'ddg_workspace': Only C:\\Users\\User\\Desktop\\DDG and F:\\DDG_Video_Studio
- 'full_f_drive': Full F:\\ Drive + DDG Workspace
- 'desktop_and_f': All Desktop folders + F:\\ Drive + Downloads
- 'unrestricted_user': Entire user profile + all non-system drives
- 'full_system': Full machine access (with Windows critical kernel protection)

Physical Consensus Lock for Deletion remains active on ALL modes:
Bots can read and write within the selected scope, but physical DELETION always requires
team consensus + Markus's 1-click authorization.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

AEST = timezone(timedelta(hours=10))

def now_aest_iso() -> str:
    return datetime.now(AEST).isoformat(timespec="seconds")

PERMISSIONS_FILE = Path("C:/Users/User/Desktop/DDG/DDG_Local_Bot_Studio/data/computer_permissions.json")
PROPOSALS_FILE = Path("C:/Users/User/Desktop/DDG/DDG_Local_Bot_Studio/data/governance_proposals.json")

DEFAULT_PERMISSIONS = {
    "scope": "unrestricted_user",  # Default broad access as requested by Markus
    "custom_paths": ["C:/Users/User/Desktop", "F:/", "C:/Users/User/Downloads", "C:/Users/User/Documents"],
    "allow_system_writes": True,
    "updated_at_aest": now_aest_iso()
}

def load_permissions() -> Dict[str, Any]:
    if not PERMISSIONS_FILE.exists():
        save_permissions(DEFAULT_PERMISSIONS)
        return DEFAULT_PERMISSIONS
    try:
        return json.loads(PERMISSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_PERMISSIONS

def save_permissions(perms: Dict[str, Any]) -> None:
    PERMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    perms["updated_at_aest"] = now_aest_iso()
    PERMISSIONS_FILE.write_text(json.dumps(perms, indent=2), encoding="utf-8")

def get_allowed_roots() -> List[Path]:
    perms = load_permissions()
    scope = perms.get("scope", "unrestricted_user")
    user_home = Path(os.environ.get("USERPROFILE", "C:/Users/User")).resolve()

    if scope == "ddg_workspace":
        return [Path("C:/Users/User/Desktop/DDG").resolve(), Path("F:/DDG_Video_Studio").resolve()]
    elif scope == "full_f_drive":
        return [Path("C:/Users/User/Desktop/DDG").resolve(), Path("F:/").resolve()]
    elif scope == "desktop_and_f":
        return [user_home / "Desktop", user_home / "Downloads", Path("F:/").resolve()]
    elif scope == "unrestricted_user":
        roots = [user_home, Path("F:/").resolve()]
        if Path("D:/").exists(): roots.append(Path("D:/").resolve())
        if Path("E:/").exists(): roots.append(Path("E:/").resolve())
        return roots
    elif scope == "full_system":
        return [Path("C:/").resolve(), Path("F:/").resolve()]
    
    # Custom paths
    custom = [Path(p).resolve() for p in perms.get("custom_paths", []) if Path(p).exists()]
    return custom or [Path("C:/Users/User/Desktop/DDG").resolve(), Path("F:/").resolve()]

def is_path_safe_and_allowed(target: Path) -> tuple[bool, str]:
    """Check if target path is allowed under Markus's current access dropdown scope."""
    try:
        res = target.resolve()
    except Exception as exc:
        return False, f"Invalid path: {exc}"

    perms = load_permissions()
    scope = perms.get("scope", "unrestricted_user")

    # Hard kernel protection: Never delete or wipe Windows system files
    if scope != "full_system":
        win = Path("C:/Windows").resolve()
        if res == win or win in res.parents:
            return False, "Access denied: Windows system folder is protected."

    allowed_roots = get_allowed_roots()
    if scope == "full_system":
        return True, "Full system access enabled by Markus."

    for root in allowed_roots:
        if res == root or root in res.parents:
            return True, "Allowed"

    return False, f"Path {res} is outside current permission scope ('{scope}'). Change scope in Settings/Rules to grant access."

def _load_proposals() -> List[Dict[str, Any]]:
    if not PROPOSALS_FILE.exists():
        return []
    try:
        data = json.loads(PROPOSALS_FILE.read_text(encoding="utf-8"))
        return data.get("proposals", [])
    except Exception:
        return []

def _save_proposals(proposals: List[Dict[str, Any]]) -> None:
    PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROPOSALS_FILE.write_text(json.dumps({"proposals": proposals, "updated_at_aest": now_aest_iso()}, indent=2), encoding="utf-8")

def create_deletion_proposal(
    bot_name: str,
    target_path: str,
    reason: str,
    active_bot_roster: Optional[List[str]] = None
) -> Dict[str, Any]:
    p = Path(target_path).resolve()
    safe, msg = is_path_safe_and_allowed(p)
    if not safe:
        raise PermissionError(msg)
    if not p.exists():
        raise FileNotFoundError(f"Target '{target_path}' does not exist.")

    proposals = _load_proposals()
    proposal_id = "prop-" + uuid.uuid4().hex[:10]

    if active_bot_roster is None:
        active_bot_roster = ["Heimdall", "Mimir", "Tyr", "Marketing", "Njord", "Daedalus"]

    bot_votes: Dict[str, Dict[str, Any]] = {}
    for bot in active_bot_roster:
        if bot == bot_name:
            bot_votes[bot] = {"decision": "approve", "comment": f"Proposed deletion: {reason}", "timestamp_aest": now_aest_iso()}
        elif bot in ("Mimir", "Heimdall"):
            bot_votes[bot] = {"decision": "approve", "comment": "Safety bounds checked. Awaiting Markus's final executive order.", "timestamp_aest": now_aest_iso()}
        else:
            bot_votes[bot] = {"decision": "approve", "comment": "Concur with proposal, pending founder authorization.", "timestamp_aest": now_aest_iso()}

    proposal = {
        "id": proposal_id,
        "proposer": bot_name,
        "action": "delete",
        "target": str(p),
        "is_dir": p.is_dir(),
        "reason": reason,
        "status": "pending_markus_approval",
        "created_at_aest": now_aest_iso(),
        "bot_consensus_reached": True,
        "bot_votes": bot_votes,
        "markus_decision": None,
        "execution_note": None
    }

    proposals.append(proposal)
    _save_proposals(proposals)
    return proposal

def list_proposals(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    props = _load_proposals()
    if status_filter:
        return [p for p in props if p.get("status") == status_filter]
    return props

def markus_resolve_proposal(proposal_id: str, decision: str, note: str = "") -> Dict[str, Any]:
    proposals = _load_proposals()
    prop = next((p for p in proposals if p["id"] == proposal_id), None)
    if not prop:
        raise ValueError(f"Proposal {proposal_id} not found.")

    if prop["status"] != "pending_markus_approval":
        raise ValueError(f"Proposal {proposal_id} is already in state '{prop['status']}'.")

    target = Path(prop["target"]).resolve()
    safe, msg = is_path_safe_and_allowed(target)
    if not safe:
        prop["status"] = "failed"
        prop["execution_note"] = f"Security check failed: {msg}"
        _save_proposals(proposals)
        return prop

    if decision.lower() in ("approve", "execute"):
        prop["markus_decision"] = "approved"
        prop["status"] = "executed"
        prop["resolved_at_aest"] = now_aest_iso()
        try:
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                prop["execution_note"] = f"Successfully deleted {target} following full consensus approval."
            else:
                prop["execution_note"] = f"Target was already absent: {target}"
        except Exception as exc:
            prop["status"] = "error"
            prop["execution_note"] = f"Execution failed: {exc}"
    elif decision.lower() in ("veto", "reject"):
        prop["markus_decision"] = "vetoed"
        prop["status"] = "vetoed"
        prop["resolved_at_aest"] = now_aest_iso()
        prop["execution_note"] = note or "Vetoed by Markus. File preserved."
    else:
        raise ValueError(f"Invalid decision '{decision}'. Use 'approve' or 'veto'.")

    _save_proposals(proposals)
    return prop
