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
        exit_kind = why if why in ("stop", "target", "daily loss stop") else ("you reversed it" if why.startswith("reversed") else "you closed it")
        for g, key in (("by_side", t.get("side")), ("by_play", t.get("play", "NONE")),
                       ("by_exit", exit_kind), ("by_confidence", _conf_bucket(t.get("confidence")))):
            groups[g].setdefault(str(key), []).append(t)
    return {"closed_trades": len(trades), "all": _stats(trades),
            **{g: {k: _stats(v) for k, v in sorted(d.items())} for g, d in groups.items()},
            "how_to_read": ("Results are % of trade size after fees, spread and funding. Groups under "
                            f"{R.MIN_SAMPLE} trades are luck, not a pattern: ignore them.")}


def veto_split(veto_log: List[Dict[str, Any]], trend_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Did the veto help? Every proposal was a real trade in the trend-rule account, so the trades Qwen skipped have a
    known result. If the skipped ones did no worse than the taken ones, the veto added nothing."""
    result = {(t["symbol"], t["opened"]): t for t in trend_trades}
    taken, skipped, open_or_unknown, not_answered = [], [], 0, 0
    for v in veto_log:
        t = result.get((v.get("symbol"), v.get("trend_opened")))
        if v.get("take") is None:
            not_answered += 1             # Qwen missed it, or the veto accounts could not have opened it anyway
        elif t is None:
            open_or_unknown += 1          # the trend rule's trade is still open (or its record was reset)
        elif v["take"]:
            taken.append(t)
        else:
            skipped.append(t)
    return {"proposals": len(veto_log), "taken": _stats(taken), "skipped": _stats(skipped),
            "still_open_or_unknown": open_or_unknown, "not_answered": not_answered,
            "how_to_read": ("Both rows are the trend rule's own results for the same trades, split by Qwen's verdict. "
                            "The veto is useful only if 'skipped' is clearly worse than 'taken'. Under "
                            f"{R.MIN_SAMPLE} trades in a row means luck, not a pattern.")}


def rank_among(equity: float, others: List[float]) -> Dict[str, Any]:
    """How many of the coin-flip accounts this account is ahead of."""
    return {"beats": sum(1 for x in others if equity > x), "of": len(others)}


def spread(values: List[float]) -> Dict[str, Any]:
    """Where the coin flips sit: the middle one and the 5% and 95% marks."""
    if not values:
        return {"n": 0}
    xs = sorted(values)
    at = lambda q: xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]
    return {"n": len(xs), "worst": round(xs[0], 2), "p5": round(at(0.05), 2), "median": round(at(0.5), 2),
            "p95": round(at(0.95), 2), "best": round(xs[-1], 2)}
