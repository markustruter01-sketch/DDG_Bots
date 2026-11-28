"""Tools a bot may use in chat (plan Phase 2.5, 26 Nov 2026).

Looking is read-only and limited by the same scope and always-blocked list as
the dashboard. The only "action" a bot can take is to PROPOSE a plan: it lands
in Waiting for you, and nothing moves until Markus approves it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from studio import pc_worker

MAX_ROWS = 40

def _fn(name: str, desc: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


PATH = {"type": "string", "description": "Full Windows path, e.g. C:\\Users\\User\\Downloads"}
TOOLS = [
    _fn("pc_look", "List what is directly inside a folder (names, sizes, dates). Read only.", {"path": PATH}, ["path"]),
    _fn("pc_sizes", "Show what takes the most space inside a folder, biggest first. Read only.", {"path": PATH}, ["path"]),
    _fn("pc_search", "Find files under a folder by name pattern, age and size. Read only.",
        {"path": PATH, "name": {"type": "string", "description": "Pattern like *.exe or *.zip; * for all"},
         "older_than_days": {"type": "number"}, "min_size_mb": {"type": "number"}}, ["path"]),
    _fn("pc_duplicates", "Find files with identical content under a folder. Read only.",
        {"path": PATH, "min_size_mb": {"type": "number"}}, ["path"]),
    _fn("pc_propose_plan", "Propose moving files or folders. Never propose deleting: use dest 'QUARANTINE' instead. "
        "Nothing moves until Markus approves it under 'Waiting for you' on the Core page (tell him that); every plan "
        "can be undone. Look at the folder first so the plan only names files a tool showed you.",
        {"title": {"type": "string"}, "reason": {"type": "string"},
         "moves": {"type": "array", "items": {"type": "object", "properties": {
             "src": {"type": "string"}, "dest": {"type": "string", "description": "New full path, or QUARANTINE"}},
             "required": ["src", "dest"]}}}, ["title", "moves"]),
]

# Read-only status tools; the server answers these (it owns the studio and crypto state).
STATUS_TOOLS = [
    _fn("studio_status", "The studio's live status: what is waiting on Markus, videos in each stage, the social queue, "
        "yesterday's routines, whether the local AI is online, and what isn't tracked yet. Read only.", {}, []),
    _fn("crypto_status", "The crypto paper-trading bot (fake money): every account's value and trades, open positions, "
        "the latest decisions, live prices and the pass bar. Read only.", {}, []),
]
CHAT_TOOLS = TOOLS + STATUS_TOOLS   # offered on every chat message since 28 Nov; the model decides when to use them


def _gb(n: Any) -> str:
    return "?" if n is None else (f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB")


def run(name: str, args: Dict[str, Any], proposer: str) -> str:
    """Run one tool; always returns short JSON text for the model."""
    try:
        if name == "pc_look":
            r = pc_worker.list_dir(str(args.get("path", "")))
            rows = [{"name": i["name"], "folder": i["is_dir"], "size": _gb(i["size"]) if i["size"] is not None else "-",
                     "changed": i["modified"], **({"blocked": i["blocked"]} if i["blocked"] else {})} for i in r["items"][:MAX_ROWS]]
            out = {"path": r["path"], "items": rows, "shown": len(rows), "total": len(r["items"])}
        elif name == "pc_sizes":
            r = pc_worker.folder_sizes(str(args.get("path", "")))
            out = {"path": r["path"], "biggest": [{"name": i["name"], "size": _gb(i["size"]), "files": i["files"]}
                                                  for i in r["items"][:MAX_ROWS]]}
        elif name == "pc_search":
            def num(k: str):
                v = args.get(k)
                return float(v) if v not in (None, "") else None
            r = pc_worker.search(str(args.get("path", "")), str(args.get("name") or "*"), num("older_than_days"), num("min_size_mb"))
            out = {"path": r["path"], "found": len(r["items"]),
                   "items": [{"path": i["path"], "size": _gb(i["size"]), "changed": i["modified"]} for i in r["items"][:MAX_ROWS]]}
        elif name == "pc_duplicates":
            r = pc_worker.find_duplicates(str(args.get("path", "")), float(args.get("min_size_mb") or 1))
            out = {"path": r["path"], "groups": len(r["groups"]), "could_free": _gb(r["wasted_total"]),
                   "examples": [{"size": _gb(g["size"]), "copies": g["copies"][:4]} for g in r["groups"][:15]]}
        elif name == "pc_propose_plan":
            moves = args.get("moves") or []
            if not isinstance(moves, list):
                raise pc_worker.WorkerError("moves must be a list")
            plan = pc_worker.create_plan(proposer, str(args.get("title") or "Tidy-up plan"), moves, str(args.get("reason") or ""))
            s = plan["summary"]
            out = {"plan_created": plan["id"], "status": "waiting for Markus to approve", "will_move": s["will_move"],
                   "blocked": s["blocked"], "warnings": s["warnings"], "size": _gb(s["bytes"]),
                   "blocked_reasons": [m["notes"] for m in plan["moves"] if m["status"] == "blocked"][:10]}
        else:
            out = {"error": f"unknown tool {name}"}
    except (pc_worker.WorkerError, FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
        out = {"error": str(exc)}
    return json.dumps(out, ensure_ascii=False)[:6000]


def describe(name: str, args: Dict[str, Any]) -> str:
    """One line for the thought panel."""
    p = args.get("path", "")
    return {"pc_look": f"Looking in {p}", "pc_sizes": f"Measuring {p}", "pc_search": f"Searching {p} for {args.get('name') or '*'}",
            "pc_duplicates": f"Checking {p} for duplicates", "pc_propose_plan": f"Writing a plan: {args.get('title', '')}",
            "studio_status": "Checking the studio's status", "crypto_status": "Reading the crypto paper bot"}.get(name, name)
