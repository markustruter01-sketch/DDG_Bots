"""Public Binance market data (no account, no keys)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

SPOT = "https://api.binance.com"
FUT = "https://fapi.binance.com"

H1_FOR_SNAPSHOT = 80        # what v3 asked for; the numbers Qwen sees must not change with the longer history below
H1_FOR_FEATURES = 750       # about 31 days of 1-hour candles, for "how wild is it compared with the last 30 days"
FUNDING_EXTREME_PCT = 0.05  # per 8 hours; the usual rate is about 0.01 (my choice of line, not a standard)


def _get(url: str, timeout: float = 6.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ddg-crypto-paper/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def book(symbols) -> Dict[str, Dict[str, float]]:
    q = urllib.parse.quote(json.dumps(list(symbols), separators=(",", ":")))
    rows = _get(f"{SPOT}/api/v3/ticker/bookTicker?symbols={q}")
    return {r["symbol"]: {"bid": float(r["bidPrice"]), "ask": float(r["askPrice"])} for r in rows}


def candles(symbol: str, interval: str, limit: int, start_ms: Optional[int] = None, end_ms: Optional[int] = None,
            timeout: float = 6.0) -> List[Dict[str, float]]:
    url = f"{SPOT}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    if start_ms is not None:
        url += f"&startTime={int(start_ms)}"
    if end_ms is not None:
        url += f"&endTime={int(end_ms)}"
    rows = _get(url, timeout)
    return [{"t": r[0], "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rows]


def funding_rate(symbol: str) -> float | None:
    """The rate being quoted for the next funding time (what Qwen is shown)."""
    try:
        return float(_get(f"{FUT}/fapi/v1/premiumIndex?symbol={symbol}")["lastFundingRate"])
    except Exception:
        return None


def funding_history(symbol: str, start_ms: Optional[int] = None, end_ms: Optional[int] = None, limit: int = 1000,
                    timeout: float = 6.0) -> List[Dict[str, float]]:
    """Funding rates that were actually charged: [{"t": funding time in ms, "rate": fraction}]."""
    url = f"{FUT}/fapi/v1/fundingRate?symbol={symbol}&limit={limit}"
    if start_ms is not None:
        url += f"&startTime={int(start_ms)}"
    if end_ms is not None:
        url += f"&endTime={int(end_ms)}"
    return [{"t": int(r["fundingTime"]), "rate": float(r["fundingRate"])} for r in _get(url, timeout)]


def settled_funding(symbol: str, slot_ms: int, tolerance_ms: int = 10 * 60 * 1000) -> float | None:
    """The rate charged at one funding time, or None if Binance has not published it (yet)."""
    try:
        for row in funding_history(symbol, slot_ms - tolerance_ms, slot_ms + tolerance_ms, limit=3):
            if abs(row["t"] - slot_ms) <= tolerance_ms:
                return row["rate"]
    except Exception:
        pass
    return None


def atr(cs: List[Dict[str, float]], n: int = 14) -> float:
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])) for p, c in zip(cs, cs[1:])]
    trs = trs[-n:]
    return sum(trs) / len(trs) if trs else 0.0


def atr_series(cs: List[Dict[str, float]], n: int = 14) -> List[float]:
    """ATR at every candle that has n candles before it (one pass)."""
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])) for p, c in zip(cs, cs[1:])]
    out, run = [], 0.0
    for i, tr in enumerate(trs):
        run += tr
        if i >= n:
            run -= trs[i - n]
        if i >= n - 1:
            out.append(run / n)
    return out


def ema(xs: List[float], n: int) -> float:
    k, e = 2 / (n + 1), xs[0]
    for x in xs[1:]:
        e = x * k + e * (1 - k)
    return e


def snapshot(symbol: str, mid: float) -> Dict[str, Any]:
    """What Qwen sees: compact, real numbers only. Completed candles only (the one still forming is left out)."""
    return views(symbol, mid)[0]


def views(symbol: str, mid: float, hour_utc: Optional[int] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(the v3 snapshot, the v4 facts) from one set of candles. Completed candles only."""
    m15 = candles(symbol, "15m", 40)[:-1]
    h1 = candles(symbol, "1h", H1_FOR_FEATURES)[:-1]
    h4 = candles(symbol, "4h", 80)[:-1]
    funding = funding_rate(symbol)
    snap = build_snapshot(symbol, mid, m15, h1[-(H1_FOR_SNAPSHOT - 1):], h4, funding)
    return snap, build_facts(symbol, mid, h1, h4, funding, hour_utc)


def build_snapshot(symbol: str, mid: float, m15, h1, h4, funding: float | None) -> Dict[str, Any]:
    pct = lambda a, b: round((a / b - 1) * 100, 3) if b else 0.0
    c1 = [c["c"] for c in h1]
    e20, e50 = ema(c1, 20), ema(c1, 50)
    a1 = atr(h1)
    vol = [c["v"] for c in h1]
    avg = sum(vol[-25:-1]) / 24 if len(vol) >= 25 else 0
    return {
        "symbol": symbol, "price": round(mid, 2),
        "change_pct": {"15m": pct(mid, m15[-1]["c"]), "1h": pct(mid, h1[-1]["c"]), "4h": pct(mid, h4[-1]["c"]),
                       "24h": pct(mid, h1[-24]["c"]) if len(h1) >= 24 else None},
        "last_8_closes_1h": [round(x, 2) for x in c1[-8:]],
        "vs_ema20_1h_pct": pct(mid, e20),
        "vs_ema50_1h_pct": pct(mid, e50),
        "ema20_vs_ema50_1h_pct": pct(e20, e50),
        "vs_ema50_4h_pct": pct(mid, ema([c["c"] for c in h4], 50)),
        "volume_last_1h_vs_24h_avg": round(vol[-1] / avg, 2) if avg else None,
        "atr14_1h": round(a1, 2),
        "atr14_1h_pct": round(a1 / mid * 100, 3) if mid else None,
        "high_low_24h": [round(max(c["h"] for c in h1[-24:]), 2), round(min(c["l"] for c in h1[-24:]), 2)],
        "funding_rate_pct": round(funding * 100, 4) if funding is not None else None,
    }


def _session(hour_utc: Optional[int]) -> Optional[str]:
    if hour_utc is None:
        return None
    return "Asia" if hour_utc < 7 else ("Europe" if hour_utc < 13 else ("US" if hour_utc < 21 else "late US"))


def build_facts(symbol: str, mid: float, h1, h4, funding: float | None, hour_utc: Optional[int] = None) -> Dict[str, Any]:
    """v4: judgements made by code, so the model does not have to do sums. Distances are in ATRs (the size of a
    normal 1-hour move), so they mean the same thing for BTC and ETH and at any price."""
    recent = h1[-(H1_FOR_SNAPSHOT - 1):]
    closes = [c["c"] for c in recent]
    a1 = atr(recent)
    if not a1 or not mid:
        return {"symbol": symbol, "note": "not enough data"}
    e20, e50 = ema(closes, 20), ema(closes, 50)
    in_atr = lambda x: round(x / a1, 2)
    gap = in_atr(e20 - e50)
    strength = abs(gap)
    e50_4h = ema([c["c"] for c in h4], 50) if h4 else mid
    # how wild is it now, against every hour of the last ~30 days
    past = atr_series(h1)
    pct_rank = round(sum(1 for x in past if x <= a1 + 1e-9) / len(past) * 100) if len(past) >= 100 else None
    day = recent[-24:]
    hi, lo = max(c["h"] for c in day), min(c["l"] for c in day)
    where = (mid - lo) / (hi - lo) if hi > lo else 0.5
    vol = [c["v"] for c in recent]
    avg = sum(vol[-25:-1]) / 24 if len(vol) >= 25 else 0
    f_pct = None if funding is None else round(funding * 100, 4)
    return {
        "symbol": symbol,
        "trend_1h": {"direction": "up" if gap > 0 else ("down" if gap < 0 else "flat"), "strength_atr": strength,
                     "label": "weak" if strength < 0.5 else ("moderate" if strength < 1.5 else "strong")},
        "trend_4h": "up" if mid > e50_4h else "down",
        "price_vs_1h_average_atr": in_atr(mid - e20),          # far above/below = already stretched
        "move_last_4h_atr": in_atr(mid - recent[-4]["c"]) if len(recent) >= 4 else None,
        "volatility": {"atr_pct_of_price": round(a1 / mid * 100, 3), "percentile_30d": pct_rank,
                       "label": None if pct_rank is None else ("quiet" if pct_rank < 25 else ("normal" if pct_rank < 75 else "wild"))},
        "range_24h": {"position_0_low_1_high": round(where, 2),
                      "label": "near the low" if where < 0.2 else ("near the high" if where > 0.8 else "middle"),
                      "to_high_atr": in_atr(hi - mid), "to_low_atr": in_atr(mid - lo)},
        "volume_last_1h_vs_24h_avg": round(vol[-1] / avg, 2) if avg else None,
        "funding": {"rate_pct_per_8h": f_pct,
                    "label": None if f_pct is None else ("extreme, longs pay" if f_pct >= FUNDING_EXTREME_PCT else
                                                         ("extreme, shorts pay" if f_pct <= -FUNDING_EXTREME_PCT else "normal"))},
        "session_utc": _session(hour_utc),
    }


def trend_rule(snap: Dict[str, Any]) -> str | None:
    """The plain-code baseline: price above a rising 1h EMA20/EMA50 -> LONG, below a falling one -> SHORT, else nothing."""
    up = snap["vs_ema20_1h_pct"] > 0 and snap["ema20_vs_ema50_1h_pct"] > 0
    down = snap["vs_ema20_1h_pct"] < 0 and snap["ema20_vs_ema50_1h_pct"] < 0
    return "LONG" if up else ("SHORT" if down else None)
