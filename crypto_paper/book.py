"""Paper account: positions, fills at bid/ask, fees, stops and targets, funding, daily loss stop.

v4: each account carries its own settings (rules.spec): the venue it trades on and the limits it obeys. Every entry goes
through `refusal` first, so the cost limits (cooldown, entries per day, one bet per direction) are plain code that no
answer from the model can get around. The same class runs live (2-second prices) and in the replay rig (1-minute candles).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from . import rules as R

MIN_NOTIONAL = 10.0   # a trade smaller than this many dollars is not opened

# What is saved and loaded. The settings (spec) and the name come from the code, never from the saved file.
STATE_FIELDS = ("started", "paused", "cash", "positions", "pending", "trades", "closed", "wins", "pnl_total", "fees",
                "funding", "day", "day_start_equity", "locked_today", "entries_today", "last_exit")


def _ts(at: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(at)).timestamp()
    except (TypeError, ValueError):
        return None


class Book:
    def __init__(self, name: str, balance: float = R.START_BALANCE, started: Optional[str] = None,
                 spec: Optional[Dict[str, Any]] = None, keep_trades: bool = True):
        self.name = name
        self.spec = dict(spec) if spec else R.spec()
        self.keep_trades = keep_trades  # False for the 200 coin flips: only the counts are kept
        self.started = started          # when this account began (a single-account reset moves it)
        self.paused = False             # paused: opens nothing new; open trades still hit their stop or target
        self.cash = balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.pending: Dict[str, Dict[str, Any]] = {}     # limit orders waiting to fill (entry style "limit")
        self.trades: List[Dict[str, Any]] = []
        self.closed = 0
        self.wins = 0
        self.pnl_total = 0.0
        self.fees = 0.0
        self.funding = 0.0
        self.day = ""
        self.day_start_equity = balance
        self.locked_today = False
        self.entries_today = 0
        self.last_exit: Dict[str, str] = {}              # coin -> time of its last exit (for the cooldown)
        self.last_refusal: Optional[str] = None          # why the last entry was refused, in plain words

    # ── saving ──
    def state(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in STATE_FIELDS}

    def load_state(self, saved: Dict[str, Any]) -> None:
        for k in STATE_FIELDS:
            if k in saved:
                setattr(self, k, saved[k])

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
            self.entries_today = 0

    def check_daily_stop(self, prices, at: str) -> Optional[str]:
        if self.locked_today:
            return None
        stop = self.spec["daily_stop"]
        if self.equity(prices) <= self.day_start_equity * (1 - stop):
            for s in list(self.positions):
                self.close(s, prices, at, "daily loss stop")
            self.pending.clear()
            self.locked_today = True
            return f"Down {stop:.0%} today: everything closed, no new trades until tomorrow."
        return None

    # ── the gate every entry passes ──
    def refusal(self, sym: str, side: str, at: str) -> Optional[str]:
        """Why this account may not open this trade now, or None. Plain code: the model cannot talk its way past it."""
        if self.locked_today:
            return "stopped for today (daily loss stop)"
        if self.paused:
            return "paused"
        if sym in self.positions:
            return "already in a trade in this coin"
        if sym in self.pending:
            return "an order is already waiting in this coin"
        if side == "SHORT" and not self.spec["allow_short"]:
            return "this account cannot sell short"
        if self.spec["one_bet"]:
            others = [p["side"] for s, p in list(self.positions.items()) + list(self.pending.items()) if s != sym]
            if side in others:
                return "same direction as a trade already open (one bet per direction)"
        cool, last = self.spec["cooldown_min"], self.last_exit.get(sym)
        if cool and last:
            t0, t1 = _ts(last), _ts(at)
            if t0 is not None and t1 is not None and t1 - t0 < cool * 60:
                return f"cooldown ({cool} min after the last exit in this coin)"
        if self.spec["max_entries"] and self.entries_today >= self.spec["max_entries"]:
            return f"entry limit for today reached ({self.spec['max_entries']})"
        return None

    # ── trading ──
    def open(self, sym: str, side: str, prices, atr: float, at: str, reason: str, funding_ok: bool,
             play: str = "NONE", confidence: Optional[float] = None) -> Optional[str]:
        """Market entry: fills now at the ask (buy) or the bid (sell), taker fee."""
        self.last_refusal = self.refusal(sym, side, at) or ("no ATR yet" if atr <= 0 else None)
        if self.last_refusal:
            return None
        px = prices[sym]["ask"] if side == "LONG" else prices[sym]["bid"]
        return self._fill(sym, side, px, prices, atr, at, reason, funding_ok, play, confidence, self.spec["taker_fee"])

    def place(self, sym: str, side: str, prices, atr: float, at: str, reason: str, funding_ok: bool,
              play: str = "NONE", confidence: Optional[float] = None) -> Optional[str]:
        """Limit entry: rests at the bid (buy) or the ask (sell). It fills only if the price trades through it."""
        self.last_refusal = self.refusal(sym, side, at) or ("no ATR yet" if atr <= 0 else None)
        if self.last_refusal:
            return None
        limit = prices[sym]["bid"] if side == "LONG" else prices[sym]["ask"]
        self.pending[sym] = {"side": side, "limit": limit, "atr": atr, "placed": at, "reason": reason,
                             "funding_ok": funding_ok, "play": play, "confidence": confidence}
        return f"limit {side} {sym} @ {limit:,.2f}"

    def enter(self, sym: str, side: str, prices, atr: float, at: str, reason: str, funding_ok: bool,
              play: str = "NONE", confidence: Optional[float] = None) -> Optional[str]:
        how = self.place if self.spec["entry"] == "limit" else self.open
        return how(sym, side, prices, atr, at, reason, funding_ok, play, confidence)

    def _fill(self, sym: str, side: str, px: float, prices, atr: float, at: str, reason: str, funding_ok: bool,
              play: str, confidence: Optional[float], fee_rate: float) -> Optional[str]:
        s = self.spec
        eq = self.equity(prices)
        stop_dist = s["stop_atr"] * atr
        qty = (eq * s["risk"]) / stop_dist
        # opening costs the fee and the spread at once, so both caps are solved with those included
        cost = fee_rate + (prices[sym]["ask"] - prices[sym]["bid"]) / px
        qty = min(qty, eq * s["max_notional"] / (px * (1 + s["max_notional"] * cost)))
        room = eq * s["max_gross"] - self.gross(prices)
        qty = min(qty, max(0.0, room) / (px * (1 + s["max_gross"] * cost)))
        if qty * px < MIN_NOTIONAL:
            self.last_refusal = "trade too small"
            return None
        fee = qty * px * fee_rate
        self.cash -= fee
        self.fees += fee
        sign = 1 if side == "LONG" else -1
        target = None if s["exits"] == "trail" else px + sign * s["target_atr"] * atr
        self.positions[sym] = {"side": side, "qty": qty, "entry": px, "opened": at, "reason": reason,
                               "stop": px - sign * stop_dist, "target": target, "atr": atr, "best": px, "be_done": False,
                               "fees": fee, "funding": 0.0, "funding_known": funding_ok,
                               "play": play, "confidence": confidence}
        self.entries_today += 1
        return f"{side} {sym} {qty:.4f} @ {px:,.2f}"

    def check_pending(self, prices, at: str) -> List[str]:
        """Fill or drop waiting limit orders. A buy fills when the ask comes down to its price; a sell when the bid rises to it."""
        notes = []
        for sym, o in list(self.pending.items()):
            if self.locked_today or self.paused:
                del self.pending[sym]
                continue
            hit = prices[sym]["ask"] <= o["limit"] if o["side"] == "LONG" else prices[sym]["bid"] >= o["limit"]
            if hit:
                del self.pending[sym]
                got = self._fill(sym, o["side"], o["limit"], prices, o["atr"], at, o["reason"], o["funding_ok"],
                                 o["play"], o["confidence"], self.spec["maker_fee"])
                notes.append(f"limit order filled: {got}" if got else f"limit order in {sym} filled too small to open")
                continue
            t0, t1 = _ts(o["placed"]), _ts(at)
            if t0 is not None and t1 is not None and t1 - t0 >= self.spec["limit_ttl_min"] * 60:
                del self.pending[sym]
                notes.append(f"limit order in {sym} not filled: dropped")
        return notes

    def close(self, sym: str, prices, at: str, why: str) -> Optional[Dict[str, Any]]:
        p = self.positions.pop(sym, None)
        if not p:
            return None
        px = prices[sym]["bid"] if p["side"] == "LONG" else prices[sym]["ask"]
        sign = 1 if p["side"] == "LONG" else -1
        gross = p["qty"] * (px - p["entry"]) * sign
        fee = p["qty"] * px * self.spec["taker_fee"]
        self.cash += gross - fee
        self.fees += fee
        t = {"symbol": sym, "side": p["side"], "qty": p["qty"], "entry": p["entry"], "exit": px, "opened": p["opened"],
             "closed": at, "why": why, "reason": p["reason"], "fees": p["fees"] + fee, "funding": p["funding"],
             "funding_known": p["funding_known"], "play": p.get("play", "NONE"),
             "confidence": p.get("confidence"), "pnl": gross - p["fees"] - fee - p["funding"]}
        self.closed += 1
        self.wins += 1 if t["pnl"] > 0 else 0
        self.pnl_total += t["pnl"]
        self.last_exit[sym] = at
        if self.keep_trades:
            self.trades.append(t)
        return t

    def _follow(self, p: Dict[str, Any], px: float) -> None:
        """Exit styles other than the fixed stop and target: move the stop behind a trade that is in front."""
        style = self.spec["exits"]
        if style == "fixed":
            return
        sign = 1 if p["side"] == "LONG" else -1
        atr = p.get("atr") or 0.0
        if (px - p.get("best", p["entry"])) * sign > 0:
            p["best"] = px
        if style == "breakeven" and not p.get("be_done") and (px - p["entry"]) * sign >= self.spec["breakeven_after_atr"] * atr:
            p["stop"], p["be_done"] = p["entry"], True
        elif style == "trail":
            trail = p["best"] - sign * self.spec["stop_atr"] * atr
            if (trail - p["stop"]) * sign > 0:
                p["stop"] = trail

    def check_exits(self, prices, at: str) -> List[Dict[str, Any]]:
        out = []
        for sym, p in list(self.positions.items()):
            bid, ask = prices[sym]["bid"], prices[sym]["ask"]
            self._follow(p, bid if p["side"] == "LONG" else ask)
            if p["side"] == "LONG":
                hit = "stop" if bid <= p["stop"] else ("target" if p["target"] is not None and bid >= p["target"] else None)
            else:
                hit = "stop" if ask >= p["stop"] else ("target" if p["target"] is not None and ask <= p["target"] else None)
            if hit:
                out.append(self.close(sym, prices, at, hit))
        return out

    def exit_on_bar(self, sym: str, o: float, h: float, low: float, half_spread: float, prices, at: str) -> Optional[Dict[str, Any]]:
        """Replay only: stop and target against one finished candle (mid prices). If both were touched, the stop counts.
        A candle that opens beyond the level fills at the open, not at the level."""
        p = self.positions.get(sym)
        if not p:
            return None
        if p["side"] == "LONG":                                   # a long is sold at the bid
            o_px, hi, lo = o - half_spread, h - half_spread, low - half_spread
            if lo <= p["stop"]:
                fill, why = min(o_px, p["stop"]), "stop"
            elif p["target"] is not None and hi >= p["target"]:
                fill, why = max(o_px, p["target"]), "target"
            else:
                self._follow(p, hi)
                return None
        else:                                                     # a short is bought back at the ask
            o_px, hi, lo = o + half_spread, h + half_spread, low + half_spread
            if hi >= p["stop"]:
                fill, why = max(o_px, p["stop"]), "stop"
            elif p["target"] is not None and lo <= p["target"]:
                fill, why = min(o_px, p["target"]), "target"
            else:
                self._follow(p, lo)
                return None
        at_fill = dict(prices)
        at_fill[sym] = {"bid": fill, "ask": fill}
        return self.close(sym, at_fill, at, why)

    def apply_funding(self, sym: str, rate: Optional[float], prices) -> None:
        p = self.positions.get(sym)
        if not p or not self.spec["funding"]:
            return
        if rate is None:
            p["funding_known"] = False
            return
        mid = (prices[sym]["bid"] + prices[sym]["ask"]) / 2
        cost = p["qty"] * mid * rate * (1 if p["side"] == "LONG" else -1)   # positive rate: longs pay shorts
        p["funding"] += cost
        self.cash -= cost
        self.funding += cost

    def act(self, sym: str, action: str, prices, atr: float, at: str, reason: str, funding_ok: bool,
            play: str = "NONE", confidence: Optional[float] = None) -> List[str]:
        """LONG / SHORT open (or keep the same side; the other side is closed first). WAIT keeps everything. CLOSE exits.
        A new trade still has to pass the limits: a refused one is noted, not opened."""
        notes = []
        cur = self.positions.get(sym)
        waiting = self.pending.get(sym)
        if waiting and (action == "CLOSE" or (action in ("LONG", "SHORT") and action != waiting["side"])):
            del self.pending[sym]
            notes.append(f"cancelled the waiting {waiting['side']} order in {sym}")
        if cur and (action == "CLOSE" or (action in ("LONG", "SHORT") and action != cur["side"])):
            t = self.close(sym, prices, at, "closed by decision" if action == "CLOSE" else "reversed to " + action)
            notes.append(f"closed {sym} {t['side']} ({t['pnl']:+,.2f})")
        if action in ("LONG", "SHORT") and sym not in self.positions and sym not in self.pending:
            o = self.enter(sym, action, prices, atr, at, reason, funding_ok, play, confidence)
            if o:
                notes.append("opened " + o)
            elif self.last_refusal:
                notes.append(f"{action} {sym} not opened: {self.last_refusal}")
        return notes

    def enter_if_flat(self, sym: str, side: Optional[str], prices, atr: float, at: str, reason: str, funding_ok: bool) -> List[str]:
        """Baselines: open only when nothing is open; exits are only the stop, the target or the daily stop."""
        if side not in ("LONG", "SHORT") or sym in self.positions or sym in self.pending:
            return []
        o = self.enter(sym, side, prices, atr, at, reason, funding_ok)
        return ["opened " + o] if o else []

    def open_view(self, prices, now) -> Dict[str, Dict[str, Any]]:
        """What Qwen is told about its own open trades."""
        out = {}
        for s, p in self.positions.items():
            mid = (prices[s]["bid"] + prices[s]["ask"]) / 2
            sign = 1 if p["side"] == "LONG" else -1
            try:
                mins = round((now - datetime.fromisoformat(p["opened"])).total_seconds() / 60)
            except (TypeError, ValueError):
                mins = None
            out[s] = {"side": p["side"], "entry": round(p["entry"], 2), "stop": round(p["stop"], 2),
                      "target": None if p["target"] is None else round(p["target"], 2),
                      "open_pct_before_exit_fee": round((mid / p["entry"] - 1) * 100 * sign, 3), "minutes_open": mins}
        return out

    def summary(self, prices) -> Dict[str, Any]:
        eq = self.equity(prices)
        return {"name": self.name, "equity": round(eq, 2), "return_pct": round((eq / R.START_BALANCE - 1) * 100, 3),
                "trades": self.closed, "win_rate": round(self.wins / self.closed * 100, 1) if self.closed else None,
                "fees": round(self.fees, 2), "funding": round(self.funding, 2), "locked_today": self.locked_today,
                "paused": self.paused, "started": self.started, "venue": self.spec["venue"],
                "entries_today": self.entries_today, "waiting_orders": len(self.pending),
                "positions": {s: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in p.items()} for s, p in self.positions.items()}}
