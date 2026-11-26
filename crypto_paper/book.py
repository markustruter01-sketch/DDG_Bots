"""Paper account: positions, fills at bid/ask, taker fees, stops and targets, funding, daily loss stop."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import rules as R


class Book:
    def __init__(self, name: str, balance: float = R.START_BALANCE):
        self.name = name
        self.cash = balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.trades: List[Dict[str, Any]] = []
        self.fees = 0.0
        self.funding = 0.0
        self.day = ""
        self.day_start_equity = balance
        self.locked_today = False

    # ── value ──
    def equity(self, prices: Dict[str, Dict[str, float]]) -> float:
        eq = self.cash
        for sym, p in self.positions.items():
            px = prices[sym]["bid"] if p["side"] == "LONG" else prices[sym]["ask"]
            eq += p["qty"] * (px - p["entry"]) * (1 if p["side"] == "LONG" else -1)
        return eq

    def gross(self, prices) -> float:
        return sum(p["qty"] * (prices[s]["bid"] + prices[s]["ask"]) / 2 for s, p in self.positions.items())

    # ── day handling ──
    def new_day(self, day: str, prices) -> None:
        if day != self.day:
            self.day, self.day_start_equity, self.locked_today = day, self.equity(prices), False

    def check_daily_stop(self, prices, at: str) -> Optional[str]:
        if self.locked_today:
            return None
        if self.equity(prices) <= self.day_start_equity * (1 - R.DAILY_LOSS_STOP):
            for s in list(self.positions):
                self.close(s, prices, at, "daily loss stop")
            self.locked_today = True
            return f"Down {R.DAILY_LOSS_STOP:.0%} today: everything closed, no new trades until tomorrow."
        return None

    # ── trading ──
    def open(self, sym: str, side: str, prices, atr: float, at: str, reason: str, funding_ok: bool) -> Optional[str]:
        if self.locked_today or sym in self.positions or atr <= 0:
            return None
        eq = self.equity(prices)
        px = prices[sym]["ask"] if side == "LONG" else prices[sym]["bid"]
        stop_dist = R.STOP_ATR * atr
        qty = (eq * R.RISK_PER_TRADE) / stop_dist
        # opening costs the fee and the spread at once, so both caps are solved with those included
        cost = R.TAKER_FEE + (prices[sym]["ask"] - prices[sym]["bid"]) / px
        qty = min(qty, eq * R.MAX_NOTIONAL_PER_POSITION / (px * (1 + R.MAX_NOTIONAL_PER_POSITION * cost)))
        room = eq * R.MAX_GROSS_LEVERAGE - self.gross(prices)
        qty = min(qty, max(0.0, room) / (px * (1 + R.MAX_GROSS_LEVERAGE * cost)))
        if qty * px < 10:
            return None
        fee = qty * px * R.TAKER_FEE
        self.cash -= fee
        self.fees += fee
        sign = 1 if side == "LONG" else -1
        self.positions[sym] = {"side": side, "qty": qty, "entry": px, "opened": at, "reason": reason,
                               "stop": px - sign * stop_dist, "target": px + sign * R.TARGET_ATR * atr,
                               "fees": fee, "funding": 0.0, "funding_known": funding_ok}
        return f"{side} {sym} {qty:.4f} @ {px:,.2f}"

    def close(self, sym: str, prices, at: str, why: str) -> Optional[Dict[str, Any]]:
        p = self.positions.pop(sym, None)
        if not p:
            return None
        px = prices[sym]["bid"] if p["side"] == "LONG" else prices[sym]["ask"]
        sign = 1 if p["side"] == "LONG" else -1
        gross = p["qty"] * (px - p["entry"]) * sign
        fee = p["qty"] * px * R.TAKER_FEE
        self.cash += gross - fee
        self.fees += fee
        t = {"symbol": sym, "side": p["side"], "qty": p["qty"], "entry": p["entry"], "exit": px, "opened": p["opened"],
             "closed": at, "why": why, "reason": p["reason"], "fees": p["fees"] + fee, "funding": p["funding"],
             "funding_known": p["funding_known"], "pnl": gross - p["fees"] - fee - p["funding"]}
        self.trades.append(t)
        return t

    def check_exits(self, prices, at: str) -> List[Dict[str, Any]]:
        out = []
        for sym, p in list(self.positions.items()):
            bid, ask = prices[sym]["bid"], prices[sym]["ask"]
            if p["side"] == "LONG":
                hit = "stop" if bid <= p["stop"] else ("target" if bid >= p["target"] else None)
            else:
                hit = "stop" if ask >= p["stop"] else ("target" if ask <= p["target"] else None)
            if hit:
                out.append(self.close(sym, prices, at, hit))
        return out

    def apply_funding(self, sym: str, rate: Optional[float], prices) -> None:
        p = self.positions.get(sym)
        if not p:
            return
        if rate is None:
            p["funding_known"] = False
            return
        mid = (prices[sym]["bid"] + prices[sym]["ask"]) / 2
        cost = p["qty"] * mid * rate * (1 if p["side"] == "LONG" else -1)   # positive rate: longs pay shorts
        p["funding"] += cost
        self.cash -= cost
        self.funding += cost

    def act(self, sym: str, action: str, prices, atr: float, at: str, reason: str, funding_ok: bool) -> List[str]:
        """LONG / SHORT / FLAT. Same side already open = hold."""
        notes = []
        cur = self.positions.get(sym)
        if cur and (action == "FLAT" or action != cur["side"]):
            t = self.close(sym, prices, at, "decision " + action)
            notes.append(f"closed {sym} {t['side']} ({t['pnl']:+,.2f})")
        if action in ("LONG", "SHORT") and sym not in self.positions:
            o = self.open(sym, action, prices, atr, at, reason, funding_ok)
            if o:
                notes.append("opened " + o)
        return notes

    def summary(self, prices) -> Dict[str, Any]:
        eq = self.equity(prices)
        wins = [t for t in self.trades if t["pnl"] > 0]
        return {"name": self.name, "equity": round(eq, 2), "return_pct": round((eq / R.START_BALANCE - 1) * 100, 3),
                "trades": len(self.trades), "win_rate": round(len(wins) / len(self.trades) * 100, 1) if self.trades else None,
                "fees": round(self.fees, 2), "funding": round(self.funding, 2), "locked_today": self.locked_today,
                "positions": {s: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in p.items()} for s, p in self.positions.items()}}
