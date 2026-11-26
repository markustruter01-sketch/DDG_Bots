"""Ask Qwen (local Ollama) for a decision. Any bad or late answer is a 'missed' decision."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import rules as R

SYSTEM = (
    "You are Plutus, a crypto trader in a PAPER-MONEY research test (no real money). Every 5 minutes you see live data "
    "for BTC and ETH and decide for each: LONG, SHORT or FLAT for the next 5 minutes or more. Code sets the size, the stop "
    "and the profit target; fees are charged on every trade, so trading too often costs money. FLAT is a fine answer. "
    "Use only the numbers given. Reply with JSON only."
)
SCHEMA = {
    "type": "object",
    "properties": {"decisions": {"type": "array", "items": {"type": "object", "properties": {
        "symbol": {"type": "string", "enum": list(R.SYMBOLS)},
        "action": {"type": "string", "enum": ["LONG", "SHORT", "FLAT"]},
        "play": {"type": "string", "enum": ["TREND", "FADE", "NONE"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"}},
        "required": ["symbol", "action", "play", "confidence", "reason"]}}},
    "required": ["decisions"],
}


def parse(text: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """Strict check. Returns {symbol: decision} for every symbol, or None."""
    try:
        data = json.loads(text)
        out = {}
        for d in data["decisions"]:
            sym, act = d["symbol"], d["action"]
            if sym in R.SYMBOLS and act in ("LONG", "SHORT", "FLAT"):
                out[sym] = {"action": act, "play": d.get("play", "NONE"),
                            "confidence": max(0.0, min(1.0, float(d.get("confidence", 0)))),
                            "reason": str(d.get("reason", ""))[:400]}
        return out if set(out) == set(R.SYMBOLS) else None
    except Exception:
        return None


def decide(snapshots: List[Dict[str, Any]], positions: Dict[str, Any], base_url: str = "http://127.0.0.1:11434") -> Tuple[Optional[Dict], Dict[str, Any]]:
    """Returns (decisions or None, info with timing and any error)."""
    user = json.dumps({"market": snapshots, "your_open_positions": positions}, ensure_ascii=False)
    body = {"model": R.MODEL, "stream": False, "think": False, "keep_alive": R.KEEP_ALIVE, "format": SCHEMA,
            "options": {"temperature": 0.3, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    t0 = time.time()
    try:
        req = urllib.request.Request(f"{base_url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=R.DECISION_TIMEOUT_S) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return None, {"seconds": round(time.time() - t0, 2), "error": f"{type(exc).__name__}: {exc}"[:200]}
    content = raw.get("message", {}).get("content", "")
    got = parse(content)
    info = {"seconds": round(time.time() - t0, 2), "tokens": raw.get("eval_count")}
    if got is None:
        info["error"] = "answer was not valid JSON with a decision for every coin"
        info["raw"] = content[:300]
    return got, info
