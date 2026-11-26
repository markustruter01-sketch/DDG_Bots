"""The journal for "Qwen + journal": plain counts from its own closed trades, worked out by code.

Qwen never writes this itself. A group shows numbers only once it has MIN_SAMPLE closed trades,
so a few lucky or unlucky trades can't steer it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import rules as R


def _conf_bucket(c: Any) -> str:
    try:
        c = float(c)
    except (TypeError, ValueError):
        return "unknown"
    return "low (<0.5)" if c < 0.5 else ("mid (0.5-0.7)" if c < 0.7 else "high (>=0.7)")


def _stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(trades)
    if n < R.MIN_SAMPLE:
        return {"trades": n, "note": f"too few to judge (needs {R.MIN_SAMPLE})"}
    pct = [t["pnl"] / (t["qty"] * t["entry"]) * 100 for t in trades]
    return {"trades": n,
            "win_rate_pct": round(sum(1 for t in trades if t["pnl"] > 0) / n * 100, 1),
            "avg_result_pct_after_costs": round(sum(pct) / n, 3),
            "total_usd": round(sum(t["pnl"] for t in trades), 2)}


def build(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Track record grouped by side, play, how the trade ended and confidence."""
    groups: Dict[str, Dict[str, List]] = {"by_side": {}, "by_play": {}, "by_exit": {}, "by_confidence": {}}
    for t in trades:
        why = t.get("why", "")
        exit_kind = "stop" if why == "stop" else ("target" if why == "target" else ("daily loss stop" if why == "daily loss stop" else "your own decision"))
        for g, key in (("by_side", t.get("side")), ("by_play", t.get("play", "NONE")),
                       ("by_exit", exit_kind), ("by_confidence", _conf_bucket(t.get("confidence")))):
            groups[g].setdefault(str(key), []).append(t)
    return {"closed_trades": len(trades), "all": _stats(trades),
            **{g: {k: _stats(v) for k, v in sorted(d.items())} for g, d in groups.items()},
            "how_to_read": ("Results are % of trade size after fees, spread and funding. Groups under "
                            f"{R.MIN_SAMPLE} trades are luck, not a pattern: ignore them.")}
