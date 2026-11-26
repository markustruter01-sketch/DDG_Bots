"""Public Binance market data (no account, no keys)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List

SPOT = "https://api.binance.com"
FUT = "https://fapi.binance.com"


def _get(url: str, timeout: float = 6.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ddg-crypto-paper/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def book(symbols) -> Dict[str, Dict[str, float]]:
    q = urllib.parse.quote(json.dumps(list(symbols), separators=(",", ":")))
    rows = _get(f"{SPOT}/api/v3/ticker/bookTicker?symbols={q}")
    return {r["symbol"]: {"bid": float(r["bidPrice"]), "ask": float(r["askPrice"])} for r in rows}


def candles(symbol: str, interval: str, limit: int) -> List[Dict[str, float]]:
    rows = _get(f"{SPOT}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    return [{"t": r[0], "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in rows]


def funding_rate(symbol: str) -> float | None:
    try:
        return float(_get(f"{FUT}/fapi/v1/premiumIndex?symbol={symbol}")["lastFundingRate"])
    except Exception:
        return None


def atr(cs: List[Dict[str, float]], n: int = 14) -> float:
    trs = [max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])) for p, c in zip(cs, cs[1:])]
    trs = trs[-n:]
    return sum(trs) / len(trs) if trs else 0.0


def ema(xs: List[float], n: int) -> float:
    k, e = 2 / (n + 1), xs[0]
    for x in xs[1:]:
        e = x * k + e * (1 - k)
    return e


def snapshot(symbol: str, mid: float) -> Dict[str, Any]:
    """What Qwen sees: compact, real numbers only. Completed candles only (the one still forming is left out)."""
    m15, h1, h4 = candles(symbol, "15m", 40)[:-1], candles(symbol, "1h", 80)[:-1], candles(symbol, "4h", 80)[:-1]
    return build_snapshot(symbol, mid, m15, h1, h4, funding_rate(symbol))


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


def trend_rule(snap: Dict[str, Any]) -> str | None:
    """The plain-code baseline: price above a rising 1h EMA20/EMA50 -> LONG, below a falling one -> SHORT, else nothing."""
    up = snap["vs_ema20_1h_pct"] > 0 and snap["ema20_vs_ema50_1h_pct"] > 0
    down = snap["vs_ema20_1h_pct"] < 0 and snap["ema20_vs_ema50_1h_pct"] < 0
    return "LONG" if up else ("SHORT" if down else None)
