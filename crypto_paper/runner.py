"""Main loop: python -m crypto_paper.runner (from the Bot Studio folder).

Every 2 s: live prices, stops and targets, daily loss stop, funding.
Every 5 min: Qwen decides; the coin flip decides; the curve gets a point.
Everything is saved, so a restart carries on where it left off.
"""

from __future__ import annotations

import json
import os
import random
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from . import brain, market
from . import rules as R
from .book import Book

AEST = timezone(timedelta(hours=10))
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DDG_CRYPTO_DATA", ROOT / "data" / "crypto"))


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


class Paper:
    def __init__(self, data: Path = DATA, decide=brain.decide, mkt=market):
        self.data, self.decide, self.mkt = data, decide, mkt
        self.qwen, self.flip = Book("Qwen"), Book("Coin flip")
        self.meta: Dict[str, Any] = {"rules_version": R.RULES_VERSION, "started": now_iso(), "hold_btc_start": None,
                                     "decisions": 0, "missed": 0, "decision_seconds": [], "last_funding_slot": "",
                                     "last_decision": None, "last_decision_slot": 0, "funding_unknown": 0}
        self.events: list = []
        self.curve: list = []
        self._load()

    # ── persistence ──
    def _load(self) -> None:
        p = self.data / "books.json"
        if not p.exists():
            return
        s = json.loads(p.read_text(encoding="utf-8"))
        if s.get("meta", {}).get("rules_version") != R.RULES_VERSION:
            p.rename(self.data / f"books_{int(time.time())}_old_rules.json")   # new rules = fresh record
            return
        self.meta.update(s["meta"])
        for b, key in ((self.qwen, "qwen"), (self.flip, "flip")):
            b.__dict__.update(s[key])
        self.events, self.curve = s.get("events", []), s.get("curve", [])

    def save(self, prices) -> None:
        _write(self.data / "books.json", {"meta": self.meta, "qwen": self.qwen.__dict__, "flip": self.flip.__dict__,
                                          "events": self.events[-200:], "curve": self.curve[-2000:]})
        btc = prices.get("BTCUSDT") if prices else None
        hold = None
        if btc and self.meta["hold_btc_start"]:
            hold = round(R.START_BALANCE * ((btc["bid"] + btc["ask"]) / 2) / self.meta["hold_btc_start"], 2)
        secs = self.meta["decision_seconds"][-50:]
        _write(self.data / "state.json", {
            "updated_at": now_iso(), "rules_version": R.RULES_VERSION, "started": self.meta["started"],
            "prices": prices, "qwen": self.qwen.summary(prices) if prices else None,
            "coin_flip": self.flip.summary(prices) if prices else None, "hold_btc": hold,
            "decisions": self.meta["decisions"], "missed": self.meta["missed"],
            "avg_decision_seconds": round(sum(secs) / len(secs), 2) if secs else None,
            "last_decision": self.meta["last_decision"], "funding_unknown": self.meta["funding_unknown"],
            "recent_trades": (self.qwen.trades[-20:])[::-1], "events": self.events[-40:][::-1], "curve": self.curve[-288:],
        })

    def log(self, kind: str, text: str, **extra) -> None:
        e = {"at": now_iso(), "kind": kind, "text": text, **extra}
        self.events.append(e)
        _append(self.data / "journal.jsonl", e)

    # ── loop steps ──
    def tick(self, prices) -> None:
        at = now_iso()
        day = datetime.now(AEST).strftime("%Y-%m-%d")
        if not self.meta["hold_btc_start"]:
            self.meta["hold_btc_start"] = (prices["BTCUSDT"]["bid"] + prices["BTCUSDT"]["ask"]) / 2
        for b in (self.qwen, self.flip):
            b.new_day(day, prices)
            for t in b.check_exits(prices, at):
                self.log("exit", f"{b.name}: {t['symbol']} {t['side']} closed at {t['why']} ({t['pnl']:+,.2f})", book=b.name)
            msg = b.check_daily_stop(prices, at)
            if msg:
                self.log("daily_stop", f"{b.name}: {msg}", book=b.name)
        utc = datetime.now(timezone.utc)
        slot = f"{utc:%Y-%m-%d}-{utc.hour:02d}"
        if utc.hour in R.FUNDING_HOURS_UTC and utc.minute == 0 and self.meta["last_funding_slot"] != slot:
            self.meta["last_funding_slot"] = slot
            for sym in R.SYMBOLS:
                rate = self.mkt.funding_rate(sym)
                if rate is None:
                    self.meta["funding_unknown"] += 1
                for b in (self.qwen, self.flip):
                    b.apply_funding(sym, rate, prices)

    def decision_round(self, prices) -> None:
        at = now_iso()
        snaps, atrs = [], {}
        for sym in R.SYMBOLS:
            mid = (prices[sym]["bid"] + prices[sym]["ask"]) / 2
            s = self.mkt.snapshot(sym, mid)
            snaps.append(s)
            atrs[sym] = s["atr14_5m"]
        funding_ok = all(self.mkt.funding_rate(s) is not None for s in R.SYMBOLS)
        self.meta["decisions"] += 1
        got, info = self.decide(snaps, {s: {"side": p["side"], "entry": p["entry"]} for s, p in self.qwen.positions.items()})
        if got is None:
            self.meta["missed"] += 1
            self.meta["last_decision"] = {"at": at, "missed": True, "why": info.get("error"), "seconds": info.get("seconds")}
            self.log("missed", f"Qwen decision missed: {info.get('error')}")
        else:
            self.meta["decision_seconds"] = (self.meta["decision_seconds"] + [info["seconds"]])[-200:]
            notes = []
            for sym, d in got.items():
                notes += self.qwen.act(sym, d["action"], prices, atrs[sym], at, d["reason"], funding_ok)
            self.meta["last_decision"] = {"at": at, "missed": False, "seconds": info["seconds"], "decisions": got, "result": notes}
            self.log("decision", "; ".join(f"{s} {d['action']}" for s, d in got.items()) + (" → " + "; ".join(notes) if notes else ""),
                     decisions=got)
        rng = random.Random(R.COIN_FLIP_SEED + self.meta["decisions"])
        for sym in R.SYMBOLS:
            for n in self.flip.act(sym, rng.choice(["LONG", "SHORT", "FLAT"]), prices, atrs[sym], at, "coin flip", funding_ok):
                self.log("flip", f"Coin flip: {n}", book="Coin flip")
        hold = R.START_BALANCE * ((prices["BTCUSDT"]["bid"] + prices["BTCUSDT"]["ask"]) / 2) / self.meta["hold_btc_start"]
        self.curve.append({"t": at, "qwen": round(self.qwen.equity(prices), 2), "flip": round(self.flip.equity(prices), 2), "hold": round(hold, 2)})


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


def _reset_if_asked() -> None:
    """data/crypto/RESET present -> archive the current record and start fresh (used once on 26 Nov)."""
    marker = DATA / "RESET"
    if marker.exists():
        stamp = int(time.time())
        for name in ("books.json", "state.json", "journal.jsonl"):
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
    p.log("start", f"Crypto paper bot started (rules {R.RULES_VERSION}).")
    prices = None
    while True:
        try:
            prices = market.book(R.SYMBOLS)
            p.tick(prices)
            slot = int(time.time()) // R.DECISION_SECONDS
            if slot != p.meta["last_decision_slot"]:
                p.meta["last_decision_slot"] = slot
                p.decision_round(prices)
            p.save(prices)
        except Exception as exc:
            p.log("error", f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
            try:
                p.save(prices)
            except Exception:
                pass
            time.sleep(10)
        time.sleep(R.TICK_SECONDS)


if __name__ == "__main__":
    main()
