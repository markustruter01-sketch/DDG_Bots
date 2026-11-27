"""Main loop: python -m crypto_paper.runner (from the Bot Studio folder).

Every 2 s: live prices, stops and targets, daily loss stop, funding.
Every 15 min, in this order:
1. Plain code (no thinking time): the coin flips and the trend rule may open a trade if they have none.
2. "Trend + Qwen veto": for each trade the trend rule has just opened, Qwen votes TAKE or SKIP. The veto accounts
   open the trade only on enough TAKE votes, so they can only ever trade less than the trend rule.
3. "Qwen" and "Qwen + journal" pick LONG / SHORT / WAIT / CLOSE as before.
Every model account trades at the price AFTER its answer arrived (v4), and stops are checked between answers.
Everything shown to Qwen and everything it answered is kept in decisions.jsonl.
Everything is saved, so a restart carries on where it left off. If the bot's own code changes on disk it stops itself,
and the watchdog starts the new version within a few minutes.
"""

from __future__ import annotations

import json
import os
import random
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import brain, controls, events, market, scorecard
from . import rules as R
from .book import Book

AEST = timezone(timedelta(hours=10))
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DDG_CRYPTO_DATA", ROOT / "data" / "crypto"))

# key -> (name on the dashboard, name in state.json, venue)
ACCOUNTS: Dict[str, Tuple[str, str, str]] = {
    "qwen": ("Qwen", "qwen", "futures"),
    "journal": ("Qwen + journal", "qwen_journal", "futures"),
    "veto": ("Trend + Qwen veto", "trend_veto", "futures"),
    "veto_spot": ("Veto, spot fees", "veto_spot", "spot"),
    "trend": ("Trend rule", "trend_rule", "futures"),
    "flip": ("Coin flip", "coin_flip", "futures"),
}
BOOKS_SAVE_EVERY_S = 60     # books.json is rewritten when something changed, and at least this often


def now_iso() -> str:
    return datetime.now(AEST).isoformat(timespec="seconds")


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _append(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def _mid(prices, sym: str) -> float:
    return (prices[sym]["bid"] + prices[sym]["ask"]) / 2


class Paper:
    def __init__(self, data: Path = DATA, decide=brain.decide, mkt=market, veto=None, digest=None):
        self.data, self.decide, self.mkt = data, decide, mkt
        real = decide is brain.decide          # tests pass their own `decide` and must never reach a real Ollama
        self.veto_fn = veto if veto is not None else (brain.veto if real else None)
        self.digest_fn = digest if digest is not None else (brain.model_digest if real else (lambda: None))
        start = now_iso()
        for key in ACCOUNTS:
            setattr(self, key, self._new_book(key, start))
        self.bank: List[Book] = [Book(f"Coin flip {i + 1}", started=start, keep_trades=False) for i in range(R.FLIP_BANK)]
        self.meta: Dict[str, Any] = {
            "rules_version": R.RULES_VERSION, "fingerprint": brain.fingerprint(), "model_digest": None, "started": start,
            "hold_btc_start": None, "decisions": 0, "missed": 0, "decision_seconds": [], "last_funding_slot": "",
            "last_decision": None, "last_decision_slot": 0, "funding_unknown": 0, "funding_skipped": 0,
            "journal_brain": {"missed": 0, "decision_seconds": [], "last_decision": None},
            "veto_brain": {"asked": 0, "missed": 0, "decision_seconds": [], "last_decision": None},
            "veto_log": [], "by_hour": {}}
        self.events: list = []
        self.curve: list = []
        self.calendar = events.load()
        self._dirty = self._bank_dirty = True
        self._books_saved_at = 0.0
        self._funding_tried_at = 0.0
        self._load()

    @staticmethod
    def _new_book(key: str, started: str) -> Book:
        name, _, venue = ACCOUNTS[key]
        return Book(name, started=started, spec=R.spec(venue))

    # ── persistence ──
    def _load(self) -> None:
        p = self.data / "books.json"
        if not p.exists():
            return
        s = json.loads(p.read_text(encoding="utf-8"))
        m = s.get("meta", {})
        if m.get("rules_version") != R.RULES_VERSION or m.get("fingerprint") != self.meta["fingerprint"]:
            stamp = int(time.time())                     # new rules or new prompts = fresh record
            p.rename(self.data / f"books_{stamp}_old_rules.json")
            bank = self.data / "flip_bank.json"
            if bank.exists():
                bank.rename(self.data / f"flip_bank_{stamp}_old_rules.json")
            return
        self.meta.update(m)
        for key, b in self.accounts().items():
            if key in s:
                b.load_state(s[key])
            if not b.started:
                b.started = self.meta["started"]
        self.events, self.curve = s.get("events", []), s.get("curve", [])
        self._load_bank()

    def _load_bank(self) -> None:
        try:
            saved = json.loads((self.data / "flip_bank.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if saved.get("fingerprint") != self.meta["fingerprint"] or len(saved.get("books", [])) != len(self.bank):
            return
        for b, st in zip(self.bank, saved["books"]):
            b.load_state(st)

    @property
    def books(self):
        return tuple(getattr(self, k) for k in ACCOUNTS)

    def accounts(self) -> Dict[str, Book]:
        return {k: getattr(self, k) for k in ACCOUNTS}

    def save(self, prices) -> None:
        now = time.time()
        if self._dirty or now - self._books_saved_at >= BOOKS_SAVE_EVERY_S:
            _write(self.data / "books.json", {"meta": self.meta, **{k: b.state() for k, b in self.accounts().items()},
                                              "events": self.events[-200:], "curve": self.curve[-2000:]})
            self._dirty, self._books_saved_at = False, now
        if self._bank_dirty:
            _write(self.data / "flip_bank.json", {"fingerprint": self.meta["fingerprint"],
                                                  "books": [b.state() for b in self.bank]})
            self._bank_dirty = False
        _write(self.data / "state.json", self._state(prices))

    def _state(self, prices) -> Dict[str, Any]:
        btc = prices.get("BTCUSDT") if prices else None
        hold = None
        if btc and self.meta["hold_btc_start"]:
            hold = round(R.START_BALANCE * ((btc["bid"] + btc["ask"]) / 2) / self.meta["hold_btc_start"], 2)
        avg = lambda xs: round(sum(xs[-50:]) / len(xs[-50:]), 2) if xs else None
        jb, vb = self.meta["journal_brain"], self.meta["veto_brain"]
        st: Dict[str, Any] = {
            "updated_at": now_iso(), "rules_version": R.RULES_VERSION, "started": self.meta["started"], "prices": prices,
            "hold_btc": hold, "pass_bar": R.PASS_BAR,
            "decisions": self.meta["decisions"], "missed": self.meta["missed"],
            "avg_decision_seconds": avg(self.meta["decision_seconds"]),
            "last_decision": self.meta["last_decision"], "funding_unknown": self.meta["funding_unknown"],
            "funding_skipped": self.meta["funding_skipped"],
            "journal_brain": {"missed": jb["missed"], "last_decision": jb["last_decision"],
                              "avg_decision_seconds": avg(jb["decision_seconds"])},
            "veto_brain": {"asked": vb["asked"], "missed": vb["missed"], "last_decision": vb["last_decision"],
                           "avg_decision_seconds": avg(vb["decision_seconds"])},
            "veto_split": scorecard.veto_split(self.meta["veto_log"], self.trend.trades),
            "veto_recent": self.meta["veto_log"][-10:][::-1],
            "scorecard": scorecard.build(self.journal.trades),
            "journal_recent_trades": (self.journal.trades[-20:])[::-1],
            "all_recent_trades": sorted((dict(t, book=b.name) for b in self.books for t in b.trades[-30:]),
                                        key=lambda t: t["closed"], reverse=True)[:30],
            "recent_trades": (self.qwen.trades[-20:])[::-1], "events": self.events[-40:][::-1], "curve": self.curve[-288:],
            "accounts": [{"key": k, "state": state, "name": name} for k, (name, state, _) in ACCOUNTS.items()],
            "limits": (f"Every account: {R.COOLDOWN_MINUTES} min cooldown after an exit in a coin, at most "
                       f"{R.MAX_ENTRIES_PER_DAY} new trades a day, and BTC and ETH in the same direction count as one bet."),
            "missed_by_hour": self.meta["by_hour"], "fingerprint": self.meta["fingerprint"],
            "model": R.MODEL, "model_digest": (self.meta["model_digest"] or "")[:19] or None,
        }
        flips = [b.equity(prices) for b in self.bank] if prices else []
        st["coin_flips"] = scorecard.spread(flips)
        st["rank_vs_flips"] = {}
        for key, (_, state, _) in ACCOUNTS.items():
            b = getattr(self, key)
            st[state] = b.summary(prices) if prices else None
            # ranked only over the same period: an account Markus reset part-way is not compared with older coin flips
            if prices and key != "flip" and b.started == self.meta["started"]:
                st["rank_vs_flips"][state] = scorecard.rank_among(b.equity(prices), flips)
        return st

    def log(self, kind: str, text: str, **extra) -> None:
        e = {"at": now_iso(), "kind": kind, "text": text, **extra}
        self.events.append(e)
        self._dirty = True
        _append(self.data / "journal.jsonl", e)

    # ── loop steps ──
    def tick(self, prices) -> None:
        at = now_iso()
        day = datetime.now(AEST).strftime("%Y-%m-%d")
        if not self.meta["hold_btc_start"]:
            self.meta["hold_btc_start"] = _mid(prices, "BTCUSDT")
            self._dirty = True
        for b in self.books:
            if b.day != day:
                self._dirty = True
            b.new_day(day, prices)
            for note in b.check_pending(prices, at):
                self.log("order", f"{b.name}: {note}", book=b.name)
            for t in b.check_exits(prices, at):
                self.log("exit", f"{b.name}: {t['symbol']} {t['side']} closed at {t['why']} ({t['pnl']:+,.2f})", book=b.name)
            msg = b.check_daily_stop(prices, at)
            if msg:
                self.log("daily_stop", f"{b.name}: {msg}", book=b.name)
        for b in self.bank:                              # the 200 coin flips: same rules, no log lines
            before = (b.day, b.closed, b.locked_today)
            b.new_day(day, prices)
            b.check_exits(prices, at)
            b.check_daily_stop(prices, at)
            if (b.day, b.closed, b.locked_today) != before:
                self._bank_dirty = True
        self._funding(prices)

    def _funding(self, prices, utc: Optional[datetime] = None) -> None:
        """Charge funding once per funding time, at the rate Binance actually settled. If the bot was not running at the
        time, or the rate never appears, open trades are flagged 'funding unknown' rather than guessed."""
        utc = utc or datetime.now(timezone.utc)
        hour = max(h for h in R.FUNDING_HOURS_UTC if h <= utc.hour)
        slot_dt = utc.replace(hour=hour, minute=0, second=0, microsecond=0)
        slot = f"{slot_dt:%Y-%m-%d}-{hour:02d}"
        last = self.meta["last_funding_slot"]
        if last == slot:
            return
        if not last:                                     # first start: nothing has been held through a funding time yet
            self.meta["last_funding_slot"] = slot
            return
        rates: Dict[str, Optional[float]] = {s: None for s in R.SYMBOLS}
        if (utc - slot_dt).total_seconds() <= R.FUNDING_GRACE_MINUTES * 60:
            if time.time() - self._funding_tried_at < 20:
                return                                   # asked a moment ago: wait before asking again
            self._funding_tried_at = time.time()
            for sym in R.SYMBOLS:
                if hasattr(self.mkt, "settled_funding"):
                    rates[sym] = self.mkt.settled_funding(sym, int(slot_dt.timestamp() * 1000))
                else:
                    rates[sym] = self.mkt.funding_rate(sym)
            if any(r is None for r in rates.values()):
                return                                   # not published yet: try again on a later price check
        else:
            self.meta["funding_skipped"] += 1
            self.log("funding", f"Funding for {slot} UTC could not be read in time: open trades are flagged, not guessed.")
        self.meta["last_funding_slot"] = slot
        self._dirty = self._bank_dirty = True
        for sym, rate in rates.items():
            if rate is None:
                self.meta["funding_unknown"] += 1
            for b in list(self.books) + self.bank:
                b.apply_funding(sym, rate, prices)

    def _fresh(self, prices):
        """Prices as they are now, with stops and targets checked against them. None if the market did not answer."""
        if not hasattr(self.mkt, "book"):
            return prices                                # test markets have no order book: time stands still
        try:
            fresh = self.mkt.book(R.SYMBOLS)
        except Exception:
            return None
        self.tick(fresh)
        return fresh

    def _hour(self, missed: bool = False) -> None:
        h = self.meta["by_hour"].setdefault(datetime.now(AEST).strftime("%H"), {"rounds": 0, "missed": 0})
        h["missed" if missed else "rounds"] += 1

    def _check_model(self) -> bool:
        """The model file is part of the rules. If Ollama now serves a different file under the same name, start fresh.
        Returns True when it did."""
        seen = self.digest_fn()
        if not seen:
            return False
        had = self.meta["model_digest"]
        if not had:
            self.meta["model_digest"], self._dirty = seen, True
        elif seen != had:
            slot = self.meta["last_decision_slot"]
            self._start_fresh(f"The model file for {R.MODEL} changed ({had[:19]} -> {seen[:19]}): old record archived, fresh record started.")
            self.meta["model_digest"], self.meta["last_decision_slot"] = seen, slot     # still one round per 15 minutes
            return True
        return False

    def decision_round(self, prices):
        """One 15-minute round. Returns the latest prices it saw."""
        if self._check_model():
            self.tick(prices)                            # the fresh accounts need their day and "hold BTC" start set first
        at = now_iso()
        utc = datetime.now(timezone.utc)
        snaps, facts, atrs = [], {}, {}
        for sym in R.SYMBOLS:
            if hasattr(self.mkt, "views"):
                s, f = self.mkt.views(sym, _mid(prices, sym), utc.hour)
            else:
                s, f = self.mkt.snapshot(sym, _mid(prices, sym)), None
            snaps.append(s)
            facts[sym] = f
            atrs[sym] = s["atr14_1h"]
        funding_ok = all(s.get("funding_rate_pct") is not None for s in snaps)
        self.meta["decisions"] += 1
        self._hour()
        self._dirty = True
        record: Dict[str, Any] = {"at": at, "round": self.meta["decisions"], "market": snaps, "facts": facts}
        quiet = events.in_blackout(utc, self.calendar)

        # 1. plain code: no thinking time, so it trades at the round's opening prices
        n = self.meta["decisions"]
        rng = random.Random(R.COIN_FLIP_SEED + n)
        trend_opened = []
        for s in snaps:
            sym = s["symbol"]
            flip_side, trend_side = rng.choice(["LONG", "SHORT", None]), self.mkt.trend_rule(s)
            if not (quiet and self.flip.spec["blackout"]):
                for note in self.flip.enter_if_flat(sym, flip_side, prices, atrs[sym], at, "coin flip", funding_ok):
                    self.log("flip", f"Coin flip: {note}", book="Coin flip")
            if not (quiet and self.trend.spec["blackout"]):
                for note in self.trend.enter_if_flat(sym, trend_side, prices, atrs[sym], at, "1h EMA20/EMA50 trend", funding_ok):
                    self.log("trend", f"Trend rule: {note}", book="Trend rule")
                    if sym in self.trend.positions:
                        trend_opened.append({"symbol": sym, "side": trend_side, "trend_opened": at})
        for i, b in enumerate(self.bank):
            r = random.Random(f"{R.COIN_FLIP_SEED}:{i}:{n}")
            for s in snaps:
                if b.enter_if_flat(s["symbol"], r.choice(["LONG", "SHORT", None]), prices, atrs[s["symbol"]], at, "coin flip", funding_ok):
                    self._bank_dirty = True
        record["trend_opened"] = trend_opened

        # 2. the veto, then 3. the two pickers. Each trades at the price after its own answer.
        prices = self._veto_round(trend_opened, snaps, facts, atrs, prices, funding_ok, record)
        prices = self._qwen_round(self.qwen, self.meta, "Qwen", None, snaps, atrs, prices, funding_ok, record)
        prices = self._qwen_round(self.journal, self.meta["journal_brain"], "Qwen + journal",
                                  scorecard.build(self.journal.trades), snaps, atrs, prices, funding_ok, record)
        hold = R.START_BALANCE * _mid(prices, "BTCUSDT") / self.meta["hold_btc_start"]
        self.curve.append({"t": at, **{k: round(b.equity(prices), 2) for k, b in self.accounts().items()}, "hold": round(hold, 2)})
        _append(self.data / "decisions.jsonl", record)
        return prices

    def _missed(self, m: Dict[str, Any], label: str, why: Optional[str], seconds: Any) -> None:
        m["missed"] += 1
        self._hour(missed=True)
        m["last_decision"] = {"at": now_iso(), "missed": True, "why": why, "seconds": seconds}
        self.log("missed", f"{label} decision missed: {why}", book=label)

    def _veto_round(self, trend_opened, snaps, facts, atrs, prices, funding_ok: bool, record: Dict[str, Any]):
        if not trend_opened or self.veto_fn is None:
            return prices
        vb = self.meta["veto_brain"]
        label, at = ACCOUNTS["veto"][0], now_iso()
        by_sym = {s["symbol"]: s for s in snaps}
        followers = (self.veto, self.veto_spot)
        cards, asked = [], []
        for prop in trend_opened:
            sym, side = prop["symbol"], prop["side"]
            if all(b.refusal(sym, side, at) for b in followers):
                # neither veto account could open it anyway (paused, cooldown, ...): don't spend a question on it
                self.meta["veto_log"].append(dict(prop, at=at, take=None, reason="veto accounts could not open it: " +
                                                  str(self.veto.refusal(sym, side, at))))
                continue
            cards.append({"symbol": sym, "side": side, "facts": facts.get(sym) or by_sym[sym]})
            asked.append(prop)
        if not cards:
            return prices
        verdicts, info = self.veto_fn(cards)
        vb["asked"] += 1
        fresh = self._fresh(prices)
        record["veto"] = {"cards": cards, "verdicts": verdicts, "info": info}
        if verdicts is None or fresh is None:
            why = info.get("error") if verdicts is None else "no fresh price after the answer"
            self._missed(vb, label, why, info.get("seconds"))
            for prop in asked:
                self.meta["veto_log"].append(dict(prop, at=at, take=None, reason="missed: " + str(why)))
            return fresh or prices
        prices, at = fresh, now_iso()
        vb["decision_seconds"] = (vb["decision_seconds"] + [info["seconds"]])[-200:]
        notes = []
        for prop in asked:
            sym, side, v = prop["symbol"], prop["side"], verdicts[prop["symbol"]]
            self.meta["veto_log"].append(dict(prop, at=at, take=bool(v["take"]), votes_take=v["votes_take"],
                                              votes_skip=v["votes_skip"], reason=v["reason"]))
            if not v["take"]:
                notes.append(f"skipped {side} {sym} ({v['votes_take']} of {info.get('votes', R.VETO_VOTES)} said take)")
                continue
            for b in followers:
                if side == "SHORT" and not b.spec["allow_short"]:
                    continue                             # a spot account simply has no short side
                o = b.enter(sym, side, prices, atrs[sym], at, f"trend rule, taken by Qwen: {v['reason']}"[:400], funding_ok,
                            "TREND", round(v["votes_take"] / max(1, info.get("votes", R.VETO_VOTES)), 2))
                notes.append(f"{b.name}: opened {o}" if o else f"{b.name}: {side} {sym} not opened: {b.last_refusal}")
        vb["last_decision"] = {"at": at, "missed": False, "seconds": info["seconds"], "verdicts": verdicts, "result": notes}
        self.log("veto", f"{label}: " + "; ".join(notes), verdicts=verdicts, book=label)
        self.save(prices)                                # keeps state.json fresh for the watchdog during a long round
        return prices

    def _qwen_round(self, book: Book, m: Dict[str, Any], label: str, track, snaps, atrs, prices, funding_ok: bool,
                    record: Dict[str, Any]):
        if book.paused:
            return prices
        pos = book.open_view(prices, datetime.now(AEST))
        now = now_iso()
        can_open = {s: [side for side in ("LONG", "SHORT") if book.refusal(s, side, now) is None] for s in R.SYMBOLS}
        must_pick = [s for s in R.SYMBOLS if s not in book.positions and s not in book.pending and can_open[s]]
        kw = {"must_pick": must_pick, "can_open": can_open}
        got, info = self.decide(snaps, pos, **kw) if track is None else self.decide(snaps, pos, track_record=track, **kw)
        fresh = self._fresh(prices)
        record[label] = {"open_positions": pos, "answer": got, "info": info}
        if got is None or fresh is None:
            self._missed(m, label, info.get("error") if got is None else "no fresh price after the answer", info.get("seconds"))
            return fresh or prices
        prices, at = fresh, now_iso()
        m["decision_seconds"] = (m["decision_seconds"] + [info["seconds"]])[-200:]
        notes = []
        for sym in must_pick:
            if got[sym]["action"] not in ("LONG", "SHORT"):           # it was told to pick a side and didn't
                m["no_pick"] = m.get("no_pick", 0) + 1
                notes.append(f"{sym}: did not pick a side ({got[sym]['action']}), so nothing opened")
        for sym, d in got.items():
            notes += book.act(sym, d["action"], prices, atrs[sym], at, d["reason"], funding_ok, d.get("play", "NONE"), d.get("confidence"))
        m["last_decision"] = {"at": at, "missed": False, "seconds": info["seconds"], "decisions": got, "result": notes}
        self.log("decision", f"{label}: " + "; ".join(f"{s} {d['action']}" for s, d in got.items())
                 + (" → " + "; ".join(notes) if notes else ""), decisions=got, book=label)
        self.save(prices)
        return prices

    # ── Markus's buttons (crypto_paper/controls.py) ──
    def apply(self, cmd: Dict[str, Any], prices) -> None:
        action, account = cmd.get("action"), cmd.get("account")
        if action not in controls.ACTIONS or account not in controls.ACCOUNTS:
            self.log("control", "Ignored a control the bot didn't recognise.")
            return
        if time.time() - float(cmd.get("at", 0)) > controls.MAX_AGE_S:
            self.log("control", f"Ignored an old '{action}' button press (the bot was off when it was sent).")
            return
        if action == "decide_now":
            self.meta["last_decision_slot"] = 0
            self.log("control", "Markus: decide now. All accounts decide on the next price check.")
            return
        if action == "reset" and account == "all":
            self.reset_all()
            return
        targets = self.accounts() if account == "all" else {account: self.accounts()[account]}
        for key, b in targets.items():
            if action == "pause":
                b.paused = True
            elif action == "resume":
                b.paused = False
            elif action == "close_trades":
                b.pending.clear()
                for sym in list(b.positions):
                    t = b.close(sym, prices, now_iso(), "closed by Markus")
                    self.log("exit", f"{b.name}: {t['symbol']} {t['side']} closed by Markus ({t['pnl']:+,.2f})", book=b.name)
            elif action == "reset":
                self._reset_account(key, b)
        words = {"pause": "paused (open trades still hit their stop or target)", "resume": "resumed",
                 "close_trades": "open trades closed", "reset": "reset to $100,000 (old account archived)"}
        who = "all accounts" if account == "all" else targets[account].name
        self.log("control", f"Markus: {who} {words[action]}.")

    def _archive(self, label: str, obj: Any) -> None:
        _write(self.data / "archive" / f"{label}_{int(time.time())}.json", obj)

    def _reset_account(self, key: str, old: Book) -> None:
        self._archive(key, old.__dict__)
        setattr(self, key, self._new_book(key, now_iso()))
        if key == "qwen":
            self.meta.update(missed=0, decision_seconds=[], last_decision=None)
        elif key == "journal":
            self.meta["journal_brain"] = {"missed": 0, "decision_seconds": [], "last_decision": None}
        elif key == "veto":
            self.meta["veto_brain"] = {"asked": 0, "missed": 0, "decision_seconds": [], "last_decision": None}
            self.meta["veto_log"] = []

    def _start_fresh(self, why: str) -> None:
        """Archive the whole record (nothing is deleted) and begin again from $100,000 everywhere."""
        self._archive("all", {"meta": self.meta, **{k: b.__dict__ for k, b in self.accounts().items()},
                              "curve": self.curve, "coin_flips": [b.state() for b in self.bank]})
        stamp = int(time.time())
        for name in ("books", "flip_bank"):
            f = self.data / f"{name}.json"
            if f.exists():
                os.replace(f, self.data / "archive" / f"{name}_{stamp}.json")
        self.__init__(self.data, self.decide, self.mkt, self.veto_fn, self.digest_fn)
        self.log("control", why)

    def reset_all(self) -> None:
        self._start_fresh("Markus: everything reset to $100,000, including hold BTC and the coin flips (old record archived).")


def _single_instance_lock():
    """Exclusive OS file lock; a second copy cannot get it and exits. (26 Nov: the old port lock let two copies run on Windows.)"""
    DATA.mkdir(parents=True, exist_ok=True)
    fh = open(DATA / "runner.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def code_signature() -> float:
    """Newest change time of the bot's own code; when it moves, the bot restarts into the new version."""
    return max((f.stat().st_mtime for f in Path(__file__).resolve().parent.glob("*.py")), default=0.0)


def _reset_if_asked() -> None:
    """data/crypto/RESET present -> archive the current record and start fresh (used once on 26 Nov)."""
    marker = DATA / "RESET"
    if marker.exists():
        stamp = int(time.time())
        for name in ("books.json", "state.json", "journal.jsonl", "flip_bank.json"):
            f = DATA / name
            if f.exists():
                f.rename(DATA / f"{f.stem}_reset_{stamp}{f.suffix}")
        marker.unlink()


def main() -> None:
    lock = _single_instance_lock()
    if lock is None:
        print("Crypto paper bot is already running.")
        return
    _reset_if_asked()
    p = Paper()
    p.log("start", f"Crypto paper bot started (rules {R.RULES_VERSION}, {p.meta['fingerprint']}).")
    prices = None
    code_at, last_code_check = code_signature(), time.time()
    last_error, last_error_at = "", 0.0
    while True:
        if time.time() - last_code_check > 30:
            last_code_check = time.time()
            if code_signature() != code_at:
                p.log("update", "Bot code updated on disk: stopping so the watchdog starts the new version.")
                lock.close()
                return
        try:
            prices = market.book(R.SYMBOLS)
            for path, cmd in controls.pending(DATA):
                try:
                    p.apply(cmd, prices)
                finally:
                    controls.file_done(path)
            p.tick(prices)
            slot = int(time.time()) // R.DECISION_SECONDS
            if slot != p.meta["last_decision_slot"]:
                p.meta["last_decision_slot"] = slot
                prices = p.decision_round(prices) or prices
            p.save(prices)
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if text != last_error or time.time() - last_error_at > 300:     # the same fault is logged once per 5 minutes
                p.log("error", text)
                traceback.print_exc()
                last_error, last_error_at = text, time.time()
            try:
                if prices:
                    p.save(prices)
            except Exception:
                pass
            time.sleep(10)
        time.sleep(R.TICK_SECONDS)


if __name__ == "__main__":
    main()
