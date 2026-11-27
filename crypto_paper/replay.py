"""Replay rig: run the same rules, accounts and prompts over past candles, in hours instead of weeks.

    python -m crypto_paper.replay download --days 90
    python -m crypto_paper.replay arms
    python -m crypto_paper.replay run --arms trend,flips,veto
    python -m crypto_paper.replay run --arms trend,flips,veto --final

How to use it honestly:
- The last 30 days are HELD OUT. A normal run stops before them. Tune on what is left.
- When one version looks best, run it ONCE with --final. That is the only number that counts. Every --final run is
  written to data/crypto/replay/final_looks.jsonl, because each extra look makes the held-out month less of a test.
- Change one thing per arm. With many arms, some will win by luck: compare against the 200 coin flips.

What is the same as live: the Book class, the limits, the trend rule, the facts and the prompts (crypto_paper.brain).
What is assumed: a fixed spread (--spread-bps); model accounts fill one minute after the decision; inside one
1-minute candle the stop counts before the target; funding as Binance settled it. Fake money, public data, no keys.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import brain, events, market, scorecard
from . import rules as R
from .book import Book

AEST = timezone(timedelta(hours=10))
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DDG_CRYPTO_DATA", ROOT / "data" / "crypto"))
MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
DAY_MS = 86_400_000
WARMUP_DAYS = 35            # the facts look back about 31 days of 1-hour candles
HOLDOUT_DAYS = 30
MODEL_DELAY_BARS = 1        # model accounts fill this many 1-minute candles after the decision
FUNDING_SLOT_MS = 8 * 3_600_000


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, AEST).isoformat(timespec="seconds")


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, AEST).strftime("%Y-%m-%d")


# ── history on disk ─────────────────────────────────────────────────────────
def _page(symbol: str, interval: str, start_ms: int, end_ms: int, log: Callable[[str], None]) -> List[List[float]]:
    rows: List[List[float]] = []
    cursor = start_ms
    while cursor < end_ms:
        got = market.candles(symbol, interval, 1000, start_ms=cursor, end_ms=end_ms - 1, timeout=20)
        if not got:
            break
        rows += [[c["t"], c["o"], c["h"], c["l"], c["c"], c["v"]] for c in got]
        cursor = int(got[-1]["t"]) + MS[interval]
        if len(got) < 1000:
            break
        time.sleep(0.2)                     # public data: stay well inside Binance's request limits
    log(f"  {symbol} {interval}: {len(rows)} candles")
    return rows


def download(days: int, folder: Path, end_ms: Optional[int] = None, log: Callable[[str], None] = print) -> None:
    """Fetch finished candles and settled funding from Binance's public API into `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    end = end_ms or int(time.time() * 1000)
    end -= end % MS["4h"]                   # stop at a 4-hour boundary so every candle in the files is finished
    start = end - days * DAY_MS
    for sym in R.SYMBOLS:
        for interval, back in (("1m", 0), ("15m", 1), ("1h", WARMUP_DAYS), ("4h", WARMUP_DAYS)):
            rows = _page(sym, interval, start - back * DAY_MS, end, log)
            _write_lines(folder / f"{sym}_{interval}.jsonl", rows)
        fund = market.funding_history(sym, start - DAY_MS, end, 1000, timeout=20)
        _write_lines(folder / f"{sym}_funding.jsonl", [[f["t"], f["rate"]] for f in fund])
        log(f"  {sym} funding: {len(fund)} settlements")
    (folder / "about.json").write_text(json.dumps({"downloaded_at": iso(int(time.time() * 1000)), "days": days,
                                                   "start_ms": start, "end_ms": end}, indent=1), encoding="utf-8")


def _write_lines(path: Path, rows: List[list]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, path)


def _read_lines(path: Path) -> List[list]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class History:
    """Past candles, answering only what was knowable at a given moment."""

    def __init__(self, minute: Dict[str, List[tuple]], bars: Dict[str, Dict[str, List[Dict[str, float]]]],
                 funding: Dict[str, List[Tuple[int, float]]]):
        self.minute = minute                        # sym -> [(t, o, h, l, c)] 1-minute candles, oldest first
        self.bars = bars                            # sym -> interval -> [candle dicts]
        self.funding = funding                      # sym -> [(funding time ms, rate)]
        self._mt = {s: [b[0] for b in rows] for s, rows in minute.items()}
        self._bt = {s: {i: [c["t"] for c in rows] for i, rows in per.items()} for s, per in bars.items()}
        self._ft = {s: [f[0] for f in rows] for s, rows in funding.items()}

    @classmethod
    def load(cls, folder: Path) -> "History":
        minute, bars, funding = {}, {}, {}
        for sym in R.SYMBOLS:
            minute[sym] = [tuple(r[:5]) for r in _read_lines(folder / f"{sym}_1m.jsonl")]
            bars[sym] = {i: [{"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
                             for r in _read_lines(folder / f"{sym}_{i}.jsonl")] for i in ("15m", "1h", "4h")}
            fpath = folder / f"{sym}_funding.jsonl"
            funding[sym] = [(int(r[0]), float(r[1])) for r in _read_lines(fpath)] if fpath.exists() else []
        return cls(minute, bars, funding)

    def span(self) -> Tuple[int, int]:
        """(first, last) moment every coin has 1-minute data for."""
        return (max(rows[0][0] for rows in self.minute.values()),
                min(rows[-1][0] + MS["1m"] for rows in self.minute.values()))

    def completed(self, sym: str, interval: str, t_ms: int, n: int) -> List[Dict[str, float]]:
        """The last n candles that had FINISHED by t_ms. A candle still forming at t_ms is never included."""
        end = bisect.bisect_right(self._bt[sym][interval], t_ms - MS[interval])
        return self.bars[sym][interval][max(0, end - n):end]

    def price_at(self, sym: str, t_ms: int) -> Optional[float]:
        """The last traded price known at t_ms: the close of the last finished 1-minute candle."""
        i = bisect.bisect_right(self._mt[sym], t_ms - MS["1m"]) - 1
        return self.minute[sym][i][4] if i >= 0 else None

    def minutes(self, sym: str, t0_ms: int, t1_ms: int) -> List[tuple]:
        ts = self._mt[sym]
        return self.minute[sym][bisect.bisect_left(ts, t0_ms):bisect.bisect_left(ts, t1_ms)]

    def funding_at(self, sym: str, slot_ms: int, tolerance_ms: int = 600_000) -> Optional[float]:
        ts = self._ft[sym]
        i = bisect.bisect_left(ts, slot_ms - tolerance_ms)
        if i < len(ts) and abs(ts[i] - slot_ms) <= tolerance_ms:
            return self.funding[sym][i][1]
        return None

    def funding_known(self, sym: str, t_ms: int) -> Optional[float]:
        """The most recent funding rate settled before t_ms (stands in for the rate being quoted at the time)."""
        i = bisect.bisect_right(self._ft[sym], t_ms) - 1
        return self.funding[sym][i][1] if i >= 0 else None


# ── remembered answers ──────────────────────────────────────────────────────
class Answers:
    """Every model answer is kept, so a re-run is instant and gives the same result, and a stopped run can resume."""

    def __init__(self, path: Path):
        self.path, self.known = path, {}
        if path.exists():
            for row in _read_lines(path):
                self.known[row["k"]] = row
        self.asked = self.reused = 0

    @staticmethod
    def key(system: str, user: str, schema: Dict[str, Any], model: str, think: bool, sample: int) -> str:
        blob = json.dumps([system, user, schema, model, think, sample], sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def asker(self, live: Optional[brain.Ask]) -> brain.Ask:
        """An `ask` for crypto_paper.brain: answer from memory, else ask `live` (None = memory only) and remember it."""
        def ask(system, user, schema, model, think, sample):
            k = self.key(system, user, schema, model, think, sample)
            hit = self.known.get(k)
            if hit is not None:
                self.reused += 1
                return hit["a"], {"seconds": hit.get("s", 0.0), "remembered": True}
            if live is None:
                return None, {"seconds": 0.0, "error": "no remembered answer, and this run may not ask the model"}
            content, info = live(system, user, schema, model, think, sample)
            self.asked += 1
            if content is not None:
                row = {"k": k, "a": content, "s": info.get("seconds", 0.0), "model": model}
                self.known[k] = row
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
            return content, info
        return ask


# ── the arms: one thing changed in each ─────────────────────────────────────
def arms() -> Dict[str, Dict[str, Any]]:
    v = {"votes": R.VETO_VOTES, "need": R.VETO_NEED}
    return {
        "trend": {"kind": "trend", "spec": R.spec(), "about": "Trend rule under the v4 limits (the live baseline)."},
        "trend_nolimits": {"kind": "trend", "spec": R.spec(cooldown_min=0, max_entries=0, one_bet=False),
                           "about": "Trend rule without cooldown, daily cap or one-bet: what the limits save or cost."},
        "trend_limit": {"kind": "trend", "spec": R.spec(entry="limit"),
                        "about": "Trend rule entering with limit orders (cheaper, but some never fill)."},
        "trend_breakeven": {"kind": "trend", "spec": R.spec(exits="breakeven"),
                            "about": f"Trend rule; stop moves to entry once {R.BREAKEVEN_AFTER_ATR} ATR in front."},
        "trend_trail": {"kind": "trend", "spec": R.spec(exits="trail"), "about": "Trend rule; stop follows the price, no target."},
        "trend_blackout": {"kind": "trend", "spec": R.spec(blackout=True),
                           "about": "Trend rule; no new trades around US rate decisions and inflation figures."},
        "trend_spot": {"kind": "trend", "spec": R.spec("spot"), "about": "Trend rule on spot: long only, Kraken-level fees."},
        "flips": {"kind": "flips", "spec": R.spec(), "n": R.FLIP_BANK, "about": f"{R.FLIP_BANK} coin-flip accounts: what luck alone looks like."},
        "veto": {"kind": "veto", "spec": R.spec(), "follow": "trend", "facts": "v4", **v,
                 "about": "Trend rule's trades, each taken only on 4 of 5 Qwen votes (the live veto account)."},
        "veto_single": {"kind": "veto", "spec": R.spec(), "follow": "trend", "facts": "v4", "votes": 1, "need": 1,
                        "about": "Veto with one answer instead of five votes."},
        "veto_numbers": {"kind": "veto", "spec": R.spec(), "follow": "trend", "facts": "v3", **v,
                         "about": "Veto shown the raw numbers instead of the code-made facts."},
        "veto_think": {"kind": "veto", "spec": R.spec(), "follow": "trend", "facts": "v4", "think": True, **v,
                       "about": "Veto with Qwen's thinking switched on (slower)."},
        "veto_spot": {"kind": "veto", "spec": R.spec("spot"), "follow": "trend", "facts": "v4", **v,
                      "about": "The veto's verdicts on spot: long only, Kraken-level fees. Uses the same answers as 'veto'."},
        "qwen": {"kind": "picker", "spec": R.spec(), "about": "Qwen picks LONG/SHORT/WAIT/CLOSE (the live Qwen account)."},
        "qwen_vote": {"kind": "picker", "spec": R.spec(), **v, "about": "Qwen picker; an action needs 4 of 5 votes, else WAIT."},
        "qwen_think": {"kind": "picker", "spec": R.spec(), "think": True, "about": "Qwen picker with thinking switched on."},
        "journal": {"kind": "picker", "spec": R.spec(), "journal": True, "about": "Qwen picker that also sees its own track record."},
    }


class Replay:
    def __init__(self, history: History, arm_keys: List[str], start_ms: int, end_ms: int, ask: Optional[brain.Ask] = None,
                 model: Optional[str] = None, spread_bps: float = 1.0, calendar=None, log: Callable[[str], None] = print):
        catalogue = arms()
        unknown = [k for k in arm_keys if k not in catalogue]
        if unknown:
            raise ValueError(f"Unknown arm(s): {unknown}. See: python -m crypto_paper.replay arms")
        keys = list(dict.fromkeys(arm_keys))
        for k in list(keys):                         # an arm that follows another needs that one in the run
            parent = catalogue[k].get("follow")
            if parent and parent not in keys:
                keys.insert(0, parent)
        order = {"trend": 0, "flips": 0, "veto": 1, "picker": 2}
        self.keys = sorted(keys, key=lambda k: order[catalogue[k]["kind"]])
        self.arms = {k: catalogue[k] for k in self.keys}
        self.h, self.ask, self.model, self.log = history, ask, model or R.MODEL, log
        self.half = spread_bps / 10_000 / 2          # half the spread, as a fraction of the price
        self.calendar = events.load() if calendar is None else calendar
        step = R.DECISION_SECONDS * 1000
        self.start = start_ms + (-start_ms) % step   # first decision on the quarter hour
        self.end = end_ms
        if any(history.price_at(s, self.start) is None for s in R.SYMBOLS):
            raise ValueError("The history has no finished 1-minute candle before the start. Start later or download more.")
        started = iso(self.start)
        self.books: Dict[str, Book] = {}
        self.banks: Dict[str, List[Book]] = {}
        for k, a in self.arms.items():
            if a["kind"] == "flips":
                self.banks[k] = [Book(f"{k} {i + 1}", started=started, spec=a["spec"], keep_trades=False) for i in range(a["n"])]
            else:
                self.books[k] = Book(k, started=started, spec=a["spec"])
        self.curves: Dict[str, List[Tuple[int, float]]] = {k: [] for k in self.books}
        self.marks: Dict[int, Dict[str, Any]] = {}   # equity and fees of every account at chosen moments
        self.veto_logs: Dict[str, List[Dict[str, Any]]] = {k: [] for k, a in self.arms.items() if a["kind"] == "veto"}
        self.missed: Dict[str, int] = {k: 0 for k, a in self.arms.items() if a["kind"] in ("veto", "picker")}
        self.rounds = 0
        self.hold_start: Optional[float] = None
        self._day = ""

    # ── prices ──
    def _px(self, mids: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        return {s: {"bid": m * (1 - self.half), "ask": m * (1 + self.half)} for s, m in mids.items()}

    def _all_books(self):
        for b in self.books.values():
            yield b
        for bank in self.banks.values():
            yield from bank

    def mark(self, t_ms: int) -> None:
        """Remember what every account is worth at t_ms (used for the period results)."""
        prices = self._px({s: self.h.price_at(s, t_ms) for s in R.SYMBOLS})
        self.marks[t_ms] = {
            "prices": prices,
            "books": {k: {"equity": b.equity(prices), "fees": b.fees, "closed": b.closed} for k, b in self.books.items()},
            "banks": {k: [b.equity(prices) for b in bank] for k, bank in self.banks.items()},
        }

    # ── one 15-minute round ──
    def round(self, t_ms: int) -> None:
        h, at = self.h, iso(t_ms)
        utc = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
        mids = {s: h.price_at(s, t_ms) for s in R.SYMBOLS}
        prices = self._px(mids)
        if self.hold_start is None:
            self.hold_start = mids["BTCUSDT"]
        snaps, facts, atrs = {}, {}, {}
        for sym in R.SYMBOLS:
            m15, h1, h4 = h.completed(sym, "15m", t_ms, 39), h.completed(sym, "1h", t_ms, market.H1_FOR_FEATURES - 1), h.completed(sym, "4h", t_ms, 79)
            fund = h.funding_known(sym, t_ms)
            snaps[sym] = market.build_snapshot(sym, mids[sym], m15, h1[-(market.H1_FOR_SNAPSHOT - 1):], h4, fund)
            facts[sym] = market.build_facts(sym, mids[sym], h1, h4, fund, utc.hour)
            atrs[sym] = snaps[sym]["atr14_1h"]
        funding_ok = all(s.get("funding_rate_pct") is not None for s in snaps.values())
        quiet = events.in_blackout(utc, self.calendar)
        self.rounds += 1
        n = self.rounds

        # plain code trades at the round's opening prices
        opened: Dict[str, List[Dict[str, Any]]] = {}
        for k, a in self.arms.items():
            if a["kind"] == "trend":
                b, opened[k] = self.books[k], []
                if quiet and b.spec["blackout"]:
                    continue
                for sym in R.SYMBOLS:
                    side = market.trend_rule(snaps[sym])
                    if b.enter_if_flat(sym, side, prices, atrs[sym], at, "1h EMA20/EMA50 trend", funding_ok) and sym in b.positions:
                        opened[k].append({"symbol": sym, "side": side, "trend_opened": at})
            elif a["kind"] == "flips":
                for i, b in enumerate(self.banks[k]):
                    r = random.Random(f"{R.COIN_FLIP_SEED}:{i}:{n}")
                    for sym in R.SYMBOLS:
                        b.enter_if_flat(sym, r.choice(["LONG", "SHORT", None]), prices, atrs[sym], at, "coin flip", funding_ok)

        # the market moves on while the model thinks
        per = {s: {b[0]: b for b in h.minutes(s, t_ms, t_ms + R.DECISION_SECONDS * 1000)} for s in R.SYMBOLS}
        both = sorted(set.intersection(*(set(d) for d in per.values())))      # minutes every coin has a candle for
        bars = [{s: per[s][t] for s in R.SYMBOLS} for t in both]
        for bar in bars[:MODEL_DELAY_BARS]:
            self._bar(bar)
        if len(bars) >= MODEL_DELAY_BARS:
            later = self._px({s: bars[MODEL_DELAY_BARS - 1][s][4] for s in R.SYMBOLS}) if MODEL_DELAY_BARS else prices
            at_later = iso(t_ms + MODEL_DELAY_BARS * MS["1m"])
            self._model_arms(opened, snaps, facts, atrs, later, at_later, funding_ok)
        for bar in bars[MODEL_DELAY_BARS:]:
            self._bar(bar)

        end_prices = self._px({s: h.price_at(s, t_ms + R.DECISION_SECONDS * 1000) or mids[s] for s in R.SYMBOLS})
        for k, b in self.books.items():
            self.curves[k].append((t_ms, b.equity(end_prices)))

    def _model_arms(self, opened, snaps, facts, atrs, prices, at: str, funding_ok: bool) -> None:
        now = datetime.fromisoformat(at)
        for k, a in self.arms.items():
            b = self.books.get(k)
            if a["kind"] == "veto":
                props = opened.get(a["follow"], [])
                cards = [{"symbol": p["symbol"], "side": p["side"],
                          "facts": facts[p["symbol"]] if a["facts"] == "v4" else snaps[p["symbol"]]} for p in props]
                if not cards:
                    continue
                verdicts, info = brain.veto(cards, votes=a["votes"], need=a["need"], budget_s=float("inf"),
                                            model=self.model, think=bool(a.get("think")), ask=self.ask or _no_model)
                if verdicts is None:
                    self.missed[k] += 1
                    self.veto_logs[k] += [dict(p, take=None) for p in props]
                    continue
                for p in props:
                    v = verdicts[p["symbol"]]
                    self.veto_logs[k].append(dict(p, take=bool(v["take"]), votes_take=v["votes_take"]))
                    if v["take"] and not (p["side"] == "SHORT" and not b.spec["allow_short"]):
                        b.enter(p["symbol"], p["side"], prices, atrs[p["symbol"]], at, "trend rule, taken by Qwen", funding_ok, "TREND")
            elif a["kind"] == "picker":
                track = scorecard.build(b.trades) if a.get("journal") else None
                view = b.open_view(prices, now)
                market_view = [snaps[s] for s in R.SYMBOLS]
                can_open = {s: [side for side in ("LONG", "SHORT") if b.refusal(s, side, at) is None] for s in R.SYMBOLS}
                if a.get("votes"):
                    got, info = brain.decide_vote(market_view, view, a["votes"], a["need"], track, self.model,
                                                  bool(a.get("think")), self.ask or _no_model)
                else:
                    got, info = brain.decide(market_view, view, track_record=track, model=self.model,
                                             think=bool(a.get("think")), ask=self.ask or _no_model, can_open=can_open)
                if got is None:
                    self.missed[k] += 1
                    continue
                for sym, d in got.items():
                    b.act(sym, d["action"], prices, atrs[sym], at, d["reason"], funding_ok, d.get("play", "NONE"), d.get("confidence"))

    def _bar(self, bar: Dict[str, tuple]) -> None:
        """One finished 1-minute candle for every account: day change, funding, waiting orders, stops and targets."""
        t0 = bar[R.SYMBOLS[0]][0]
        at = iso(t0 + MS["1m"])
        opens = self._px({s: bar[s][1] for s in R.SYMBOLS})
        closes = self._px({s: bar[s][4] for s in R.SYMBOLS})
        day = day_of(t0)
        if day != self._day:
            self._day = day
            for b in self._all_books():
                b.new_day(day, opens)
        if t0 % FUNDING_SLOT_MS == 0:
            for sym in R.SYMBOLS:
                rate = self.h.funding_at(sym, t0)
                for b in self._all_books():
                    if sym in b.positions:
                        b.apply_funding(sym, rate, opens)
        for b in self._all_books():
            if not b.positions and not b.pending:
                continue
            if b.pending:
                # a buy order is tested against the candle's low, a sell order against its high
                worst = dict(closes)
                for sym, o in b.pending.items():
                    edge = bar[sym][3] if o["side"] == "LONG" else bar[sym][2]
                    worst[sym] = {"bid": edge * (1 - self.half), "ask": edge * (1 + self.half)}
                b.check_pending(worst, at)
            for sym in list(b.positions):
                _, o, hi, lo, _c = bar[sym]
                b.exit_on_bar(sym, o, hi, lo, bar[sym][4] * self.half, closes, at)
            if b.positions:
                b.check_daily_stop(closes, at)

    def run(self, marks: Tuple[int, ...] = ()) -> None:
        step = R.DECISION_SECONDS * 1000
        want = sorted(set(marks) | {self.start, self.end})
        total = max(1, (self.end - self.start) // step)
        t, done, began = self.start, 0, time.time()
        while t < self.end:
            while want and want[0] <= t:
                self.mark(want.pop(0))
            self.round(t)
            t += step
            done += 1
            if done % 500 == 0:
                self.log(f"  {done}/{total} rounds ({time.time() - began:.0f} s)")
        for m in want:
            self.mark(m)

    # ── results ──
    def results(self, t0: int, t1: int) -> Dict[str, Any]:
        """Every arm's result between two marked moments."""
        a, b = self.marks[t0], self.marks[t1]
        t0_iso, t1_iso = iso(t0), iso(t1)
        flips = {k: [(e1 / e0 - 1) * 100 for e0, e1 in zip(a["banks"][k], b["banks"][k])] for k in self.banks}
        luck = next(iter(flips.values()), [])
        out: Dict[str, Any] = {"from": t0_iso, "to": t1_iso, "arms": {}, "coin_flips": {k: scorecard.spread(v) for k, v in flips.items()}}
        btc0, btc1 = a["prices"]["BTCUSDT"], b["prices"]["BTCUSDT"]
        out["hold_btc_pct"] = round(((btc1["bid"] + btc1["ask"]) / (btc0["bid"] + btc0["ask"]) - 1) * 100, 2)
        for k, book in self.books.items():
            e0, e1 = a["books"][k]["equity"], b["books"][k]["equity"]
            trades = [t for t in book.trades if t0_iso < t["closed"] <= t1_iso]
            pct = [t["pnl"] / (t["qty"] * t["entry"]) * 100 for t in trades]
            curve = [e for (t, e) in self.curves[k] if t0 <= t < t1]
            peak, drop = e0, 0.0
            for e in curve:
                peak = max(peak, e)
                drop = max(drop, (peak - e) / peak * 100)
            ret = (e1 / e0 - 1) * 100
            row = {"about": self.arms[k]["about"], "return_pct": round(ret, 2), "trades": len(trades),
                   "won_pct": round(sum(1 for t in trades if t["pnl"] > 0) / len(trades) * 100, 1) if trades else None,
                   "avg_trade_pct": round(sum(pct) / len(pct), 3) if pct else None,
                   "fees": round(b["books"][k]["fees"] - a["books"][k]["fees"], 2), "worst_drop_pct": round(drop, 2)}
            if luck:
                row["beats_flips"] = f"{sum(1 for x in luck if ret > x)} of {len(luck)}"
            if k in self.missed:
                row["missed"] = self.missed[k]
            if k in self.veto_logs:
                parent = self.books[self.arms[k]["follow"]]
                log = [v for v in self.veto_logs[k] if t0_iso <= v["trend_opened"] < t1_iso]
                row["veto_check"] = scorecard.veto_split(log, parent.trades)
            out["arms"][k] = row
        return out


def _no_model(system, user, schema, model, think, sample):
    return None, {"seconds": 0.0, "error": "this run has no model to ask"}


# ── report ──────────────────────────────────────────────────────────────────
def report_md(meta: Dict[str, Any], periods: Dict[str, Dict[str, Any]]) -> str:
    cell = lambda v, unit="": "—" if v is None else f"{v}{unit}"
    lines = ["# Crypto replay report", "",
             f"- Run: {meta['run_id']} · model `{meta['model']}` · rules {meta['rules_version']} ({meta['fingerprint']})",
             f"- Assumed: spread {meta['spread_bps']} bp; model accounts fill {MODEL_DELAY_BARS} minute after the decision; "
             "inside one minute the stop counts before the target. Fake money.",
             f"- Model answers: {meta['asked']} asked now, {meta['reused']} reused from earlier runs.", ""]
    if "held_out" not in periods:
        lines += [f"**The last {meta['holdout_days']} days were not touched.** Tune on the table below. "
                  "Run with `--final` once, when you have picked one version.", ""]
    for name, title in (("tune", "Tune period"), ("held_out", "HELD-OUT period (the number that counts)")):
        p = periods.get(name)
        if not p:
            continue
        lines += [f"## {title}: {p['from'][:16]} to {p['to'][:16]}", "",
                  f"Hold BTC over the same time: {p['hold_btc_pct']:+.2f}%", ""]
        for k, s in p["coin_flips"].items():
            if s.get("n"):
                lines.append(f"Coin flips ({s['n']}): worst {s['worst']:+.2f}%, 5% mark {s['p5']:+.2f}%, middle {s['median']:+.2f}%, "
                             f"95% mark {s['p95']:+.2f}%, best {s['best']:+.2f}%")
        lines += ["", "| Arm | Return | Trades | Won | Avg trade | Fees | Worst drop | Beats flips | Missed |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for k, r in p["arms"].items():
            lines.append(f"| `{k}` | {r['return_pct']:+.2f}% | {r['trades']} | {cell(r['won_pct'], '%')} | {cell(r['avg_trade_pct'], '%')} | "
                         f"${r['fees']:,.0f} | {r['worst_drop_pct']:.2f}% | {r.get('beats_flips', '—')} | {r.get('missed', '—')} |")
        checks = [(k, r["veto_check"]) for k, r in p["arms"].items() if "veto_check" in r]
        if checks:
            lines += ["", "**Did the veto help?** Both columns are the trend rule's own results for the same trades.", ""]
            for k, c in checks:
                show = lambda g: (f"{g['trades']} trades, {g['avg_result_pct_after_costs']:+.3f}% avg, {g['win_rate_pct']}% won"
                                  if "win_rate_pct" in g else f"{g['trades']} trades (too few to judge)")
                lines.append(f"- `{k}`: taken {show(c['taken'])} · skipped {show(c['skipped'])} · no answer {c['not_answered']}")
        lines.append("")
    lines += ["## What each arm is", ""] + [f"- `{k}`: {a}" for k, a in meta["arms"].items()]
    lines += ["", "## How to read this", "",
              "- A result means something only if it beats most of the coin flips AND the plain trend rule.",
              "- 'Avg trade' is after fees, spread and funding, as a share of the trade's size.",
              "- The veto is useful only if the trades it skipped did clearly worse than the trades it took.",
              "- One change per arm. The more arms you try, the more likely one wins by luck.",
              "- A good tune result is a reason to run `--final` once. It is not a result.", ""]
    return "\n".join(lines)


# ── command line ────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m crypto_paper.replay", description="Replay the crypto paper bot over past candles.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="fetch past candles and funding from Binance (public data, no keys)")
    d.add_argument("--days", type=int, default=90)
    sub.add_parser("arms", help="list what can be compared")
    r = sub.add_parser("run", help="run arms over the downloaded history")
    r.add_argument("--arms", default="trend,flips,veto", help="comma-separated arm names (see: arms)")
    r.add_argument("--model", default=None, help=f"Ollama model for the model arms (default {R.MODEL})")
    r.add_argument("--final", action="store_true", help=f"also run the held-out last {HOLDOUT_DAYS} days (look once)")
    r.add_argument("--holdout-days", type=int, default=HOLDOUT_DAYS)
    r.add_argument("--spread-bps", type=float, default=1.0)
    r.add_argument("--memory-only", action="store_true", help="never ask the model; use remembered answers only")
    args = ap.parse_args(argv)
    hist_dir, out_dir = DATA / "history", DATA / "replay"

    if args.cmd == "arms":
        for k, a in arms().items():
            print(f"{k:16} {a['about']}")
        return 0
    if args.cmd == "download":
        print(f"Downloading {args.days} days (plus {WARMUP_DAYS} days of warm-up) into {hist_dir} ...")
        download(args.days, hist_dir)
        print("Done.")
        return 0

    history = History.load(hist_dir)
    first, last = history.span()
    first += R.DECISION_SECONDS * 1000          # the first decision needs a finished candle before it
    split = last - args.holdout_days * DAY_MS
    if split <= first:
        print("Not enough history for a held-out period. Download more days.")
        return 1
    keys = [k.strip() for k in args.arms.split(",") if k.strip()]
    answers = Answers(out_dir / "answers.jsonl")
    live = None if args.memory_only else brain.ask_ollama
    model = args.model or R.MODEL
    run_id = datetime.now(AEST).strftime("%Y%m%d-%H%M%S") + ("-final" if args.final else "-tune")
    end = last if args.final else split
    rp = Replay(history, keys, first, end, ask=answers.asker(live), model=model, spread_bps=args.spread_bps)
    print(f"Run {run_id}: {', '.join(rp.keys)} · {iso(rp.start)[:16]} to {iso(end)[:16]} · model {model}")
    rp.run(marks=(split,) if args.final else ())
    periods = {"tune": rp.results(rp.start, split if args.final else end)}
    if args.final:
        periods["held_out"] = rp.results(split, end)
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "final_looks.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": iso(int(time.time() * 1000)), "run": run_id, "arms": rp.keys, "model": model}) + "\n")
    meta = {"run_id": run_id, "model": model, "rules_version": R.RULES_VERSION, "fingerprint": brain.fingerprint(),
            "spread_bps": args.spread_bps, "holdout_days": args.holdout_days, "asked": answers.asked, "reused": answers.reused,
            "arms": {k: a["about"] for k, a in rp.arms.items()}}
    folder = out_dir / run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps({"meta": meta, "periods": periods}, indent=1), encoding="utf-8")
    text = report_md(meta, periods)
    (folder / "report.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved to {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
