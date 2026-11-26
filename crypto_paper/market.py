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
    """What Qwen sees: compact, real numbers only."""
    m1, m5, h1 = candles(symbol, "1m", 60), candles(symbol, "5m", 60), candles(symbol, "1h", 50)
    pct = lambda a, b: round((a / b - 1) * 100, 3) if b else 0.0
    vol5 = [c["v"] for c in m5]
    return {
        "symbol": symbol, "price": round(mid, 2),
        "change_pct": {"1m": pct(mid, m1[-2]["c"]), "5m": pct(mid, m5[-2]["c"]), "15m": pct(mid, m5[-4]["c"]),
                       "1h": pct(mid, h1[-2]["c"]), "24h": pct(mid, h1[-25]["c"]) if len(h1) >= 25 else None},
        "last_12_closes_5m": [round(c["c"], 2) for c in m5[-12:]],
        "vs_ema20_5m_pct": pct(mid, ema([c["c"] for c in m5], 20)),
        "vs_ema50_1h_pct": pct(mid, ema([c["c"] for c in h1], 50)),
        "volume_5m_vs_avg": round(vol5[-2] / (sum(vol5[-26:-2]) / 24), 2) if sum(vol5[-26:-2]) else None,
        "atr14_5m": round(atr(m5), 2),
        "high_low_1h": [round(max(c["h"] for c in m5[-12:]), 2), round(min(c["l"] for c in m5[-12:]), 2)],
    }
