"""Replay rig: no look-ahead, same rules as live, remembered answers, tune / held-out split. No network, no model."""

from __future__ import annotations

import json
import math
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crypto_paper import market, replay  # noqa: E402
from crypto_paper import rules as R  # noqa: E402

MIN = 60_000
T0 = 1_780_000_000_000 - 1_780_000_000_000 % (4 * 3_600_000)      # a 4-hour boundary
DAYS = 40                                                            # 35 days of warm-up + 5 days to replay
START = T0 + 35 * replay.DAY_MS
END = T0 + DAYS * replay.DAY_MS


def minute_candles(seed: int, base: float) -> list:
    """A made-up price path with trends and chop, as 1-minute candles."""
    rnd, price, rows = random.Random(seed), base, []
    for i in range(DAYS * 1440):
        drift = 0.00004 * math.sin(i / 900.0) + 0.00002 * math.sin(i / 211.0)
        o = price
        c = o * (1 + drift + rnd.gauss(0, 0.0006))
        hi, lo = max(o, c) * (1 + abs(rnd.gauss(0, 0.0003))), min(o, c) * (1 - abs(rnd.gauss(0, 0.0003)))
        rows.append((T0 + i * MIN, o, hi, lo, c))
        price = c
    return rows


def bigger(rows: list, interval_ms: int) -> list:
    out, cur = [], None
    for t, o, h, low, c in rows:
        start = t - t % interval_ms
        if cur is None or cur["t"] != start:
            cur = {"t": start, "o": o, "h": h, "l": low, "c": c, "v": 0.0}
            out.append(cur)
        cur["h"], cur["l"], cur["c"], cur["v"] = max(cur["h"], h), min(cur["l"], low), c, cur["v"] + 1.0
    return out


def make_history(minute=None) -> replay.History:
    minute = minute or {"BTCUSDT": minute_candles(1, 60000.0), "ETHUSDT": minute_candles(2, 3000.0)}
    bars = {s: {i: bigger(rows, replay.MS[i]) for i in ("15m", "1h", "4h")} for s, rows in minute.items()}
    funding = {s: [(t, 0.0001) for t in range(T0, END, replay.FUNDING_SLOT_MS)] for s in minute}
    return replay.History(minute, bars, funding)


HISTORY = make_history()


def verdict_ask(word: str):
    def ask(system, user, schema, model, think, sample):
        if "proposed_trades" in user:
            cards = json.loads(user)["proposed_trades"]
            return json.dumps({"verdicts": [{"symbol": c["symbol"], "verdict": word, "reason": "test"} for c in cards]}), {"seconds": 0.1}
        return json.dumps({"decisions": [{"symbol": s, "action": "WAIT", "play": "NONE", "confidence": 0.1, "reason": "t"}
                                         for s in R.SYMBOLS]}), {"seconds": 0.1}
    return ask


class SmallBank(unittest.TestCase):
    def setUp(self) -> None:
        self._bank = R.FLIP_BANK
        R.FLIP_BANK = 12                 # enough to test with; the real number is 200

    def tearDown(self) -> None:
        R.FLIP_BANK = self._bank


class TestHistory(unittest.TestCase):
    def test_a_candle_still_forming_is_never_served(self) -> None:
        t = START + 20 * MIN                                             # 20 minutes into an hour
        last = HISTORY.completed("BTCUSDT", "1h", t, 5)[-1]
        self.assertEqual(last["t"], START - 3_600_000)                   # the hour that ended at START, not the one running
        self.assertEqual(HISTORY.completed("BTCUSDT", "15m", t, 1)[0]["t"], START)
        self.assertEqual(HISTORY.price_at("BTCUSDT", t), HISTORY.minute["BTCUSDT"][35 * 1440 + 19][4])
        self.assertEqual(len(HISTORY.completed("BTCUSDT", "1h", START, market.H1_FOR_FEATURES - 1)), market.H1_FOR_FEATURES - 1)

    def test_funding_lookup(self) -> None:
        self.assertEqual(HISTORY.funding_at("BTCUSDT", START), 0.0001)
        self.assertIsNone(HISTORY.funding_at("BTCUSDT", START + 3_600_000))


class TestReplay(SmallBank):
    def run_arms(self, keys, ask=None, history=HISTORY, end=END):
        rp = replay.Replay(history, keys, START, end, ask=ask, log=lambda s: None, calendar=[])
        rp.run()
        return rp

    def test_the_future_cannot_change_the_past(self) -> None:
        cut = START + 2 * replay.DAY_MS
        a = self.run_arms(["trend", "flips"], end=cut)
        scrambled = {s: [r if r[0] < cut else (r[0], r[1] * 3, r[2] * 3, r[3] * 3, r[4] * 3) for r in rows]
                     for s, rows in HISTORY.minute.items()}
        b = self.run_arms(["trend", "flips"], history=make_history(scrambled), end=cut)
        self.assertGreater(len(a.books["trend"].trades), 0)
        self.assertEqual(a.books["trend"].trades, b.books["trend"].trades)
        self.assertEqual(a.marks[cut]["books"], b.marks[cut]["books"])
        self.assertEqual(a.marks[cut]["banks"], b.marks[cut]["banks"])

    def test_same_rules_as_live(self) -> None:
        rp = self.run_arms(["trend", "trend_nolimits", "trend_spot", "flips"])
        trend, free, spot = rp.books["trend"], rp.books["trend_nolimits"], rp.books["trend_spot"]
        self.assertGreater(trend.closed, 3)
        self.assertGreaterEqual(free.closed, trend.closed)               # the limits can only remove trades
        self.assertTrue(all(t["side"] == "LONG" for t in spot.trades))   # spot never shorts
        self.assertGreater(spot.fees / max(1, spot.closed), trend.fees / max(1, trend.closed))
        for t in trend.trades:                                           # every exit is a stop, a target or the daily stop
            self.assertIn(t["why"], ("stop", "target", "daily loss stop"))
        by_coin = {}
        for t in sorted(trend.trades, key=lambda t: t["opened"]):        # cooldown respected between trades in a coin
            if t["symbol"] in by_coin:
                gap = (replay.datetime.fromisoformat(t["opened"]) - replay.datetime.fromisoformat(by_coin[t["symbol"]])).total_seconds()
                self.assertGreaterEqual(gap, R.COOLDOWN_MINUTES * 60)
            by_coin[t["symbol"]] = t["closed"]
        self.assertEqual(len(rp.banks["flips"]), 12)
        self.assertGreater(len({round(b.equity(rp.marks[END]["prices"]), 2) for b in rp.banks["flips"]}), 6)

    def test_veto_only_ever_trades_less_than_the_trend_rule(self) -> None:
        take = self.run_arms(["veto", "veto_spot"], ask=verdict_ask("TAKE"))
        skip = self.run_arms(["veto"], ask=verdict_ask("SKIP"))
        none = self.run_arms(["veto"], ask=None)
        self.assertEqual(take.keys[0], "trend")                          # the arm it follows was added for it
        opened = {(t["symbol"], t["side"]) for t in take.books["trend"].trades}
        self.assertTrue(take.books["veto"].trades)
        for t in take.books["veto"].trades:
            self.assertIn((t["symbol"], t["side"]), opened)
        self.assertLessEqual(take.books["veto"].closed + len(take.books["veto"].positions),
                             take.books["trend"].closed + len(take.books["trend"].positions))
        self.assertTrue(all(t["side"] == "LONG" for t in take.books["veto_spot"].trades))
        self.assertEqual((skip.books["veto"].closed, skip.books["veto"].positions), (0, {}))
        self.assertEqual(none.books["veto"].closed, 0)                   # no model = nothing opened, counted as missed
        self.assertGreater(none.missed["veto"], 0)
        res = take.results(take.start, END)
        self.assertIn("veto_check", res["arms"]["veto"])
        self.assertEqual(res["arms"]["veto"]["veto_check"]["skipped"]["trades"], 0)

    def test_model_accounts_fill_a_minute_later(self) -> None:
        rp = self.run_arms(["veto"], ask=verdict_ask("TAKE"))
        first_trend = min(rp.books["trend"].trades, key=lambda t: t["opened"])
        first_veto = min(rp.books["veto"].trades, key=lambda t: t["opened"])
        gap = (replay.datetime.fromisoformat(first_veto["opened"]) - replay.datetime.fromisoformat(first_trend["opened"])).total_seconds()
        self.assertEqual(gap, 60 * replay.MODEL_DELAY_BARS)

    def test_limit_and_exit_arms_run(self) -> None:
        rp = self.run_arms(["trend", "trend_limit", "trend_breakeven", "trend_trail", "trend_blackout"])
        self.assertGreater(rp.books["trend_limit"].closed, 0)
        self.assertLess(rp.books["trend_limit"].fees / rp.books["trend_limit"].closed, rp.books["trend"].fees / rp.books["trend"].closed)
        self.assertTrue(all(t["why"] != "target" for t in rp.books["trend_trail"].trades))
        self.assertGreater(rp.books["trend_breakeven"].closed, 0)

    def test_remembered_answers_reproduce_the_run_without_the_model(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            mem = replay.Answers(tmp / "answers.jsonl")
            first = self.run_arms(["veto"], ask=mem.asker(verdict_ask("TAKE")))
            self.assertGreater(mem.asked, 0)
            again = replay.Answers(tmp / "answers.jsonl")
            second = self.run_arms(["veto"], ask=again.asker(None))       # memory only
            self.assertEqual((again.asked, again.reused > 0), (0, True))
            self.assertEqual(first.books["veto"].trades, second.books["veto"].trades)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unknown_arm_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            replay.Replay(HISTORY, ["moon"], START, END)


class TestCommandLine(SmallBank):
    def setUp(self) -> None:
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self._data = replay.DATA
        replay.DATA = self.tmp
        hist = self.tmp / "history"
        hist.mkdir()
        for sym, rows in HISTORY.minute.items():
            window = [r for r in rows if r[0] >= START]
            replay._write_lines(hist / f"{sym}_1m.jsonl", [list(r) + [1.0] for r in window])
            for i in ("15m", "1h", "4h"):
                replay._write_lines(hist / f"{sym}_{i}.jsonl", [[c["t"], c["o"], c["h"], c["l"], c["c"], c["v"]] for c in HISTORY.bars[sym][i]])
            replay._write_lines(hist / f"{sym}_funding.jsonl", [list(f) for f in HISTORY.funding[sym]])

    def tearDown(self) -> None:
        replay.DATA = self._data
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def reports(self):
        return sorted((self.tmp / "replay").glob("*/report.json"))

    def test_normal_run_never_touches_the_held_out_days(self) -> None:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = replay.main(["run", "--arms", "trend,flips", "--holdout-days", "2", "--memory-only"])
        self.assertEqual(code, 0)
        rep = json.loads(self.reports()[0].read_text())
        self.assertEqual(list(rep["periods"]), ["tune"])
        self.assertLessEqual(rep["periods"]["tune"]["to"], replay.iso(END - 2 * replay.DAY_MS))
        self.assertIn("were not touched", out.getvalue())
        self.assertFalse((self.tmp / "replay" / "final_looks.jsonl").exists())

    def test_final_run_reports_both_periods_and_is_counted(self) -> None:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as out:
            replay.main(["run", "--arms", "trend,flips", "--holdout-days", "2", "--memory-only", "--final"])
        rep = json.loads(self.reports()[0].read_text())
        self.assertEqual(list(rep["periods"]), ["tune", "held_out"])
        self.assertEqual(rep["periods"]["tune"]["to"], rep["periods"]["held_out"]["from"])
        self.assertIn("beats_flips", rep["periods"]["held_out"]["arms"]["trend"])
        self.assertIn("HELD-OUT", out.getvalue())
        looks = (self.tmp / "replay" / "final_looks.jsonl").read_text().splitlines()
        self.assertEqual(len(looks), 1)

    def test_download_writes_finished_candles_only(self) -> None:
        calls = []
        def fake_candles(symbol, interval, limit, start_ms=None, end_ms=None, timeout=6.0):
            calls.append((symbol, interval, start_ms, end_ms))
            step = replay.MS[interval]
            first = start_ms + (-start_ms) % step
            return [{"t": t, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 3.0} for t in range(first, min(end_ms + 1, first + limit * step), step)]
        real_c, real_f, real_sleep = market.candles, market.funding_history, replay.time.sleep
        market.candles, market.funding_history = fake_candles, lambda *a, **k: [{"t": END, "rate": 0.0001}]
        replay.time.sleep = lambda s: None
        try:
            out = self.tmp / "dl"
            replay.download(2, out, end_ms=END + 12345, log=lambda s: None)
        finally:
            market.candles, market.funding_history, replay.time.sleep = real_c, real_f, real_sleep
        rows = replay._read_lines(out / "BTCUSDT_1m.jsonl")
        self.assertEqual(len(rows), 2 * 1440)
        self.assertEqual(rows[-1][0], END - MIN)                         # the last candle ended at the 4-hour boundary
        self.assertEqual(len(replay._read_lines(out / "ETHUSDT_1h.jsonl")), (2 + replay.WARMUP_DAYS) * 24)
        self.assertTrue(all(e is not None and e < END for (_, _, _, e) in calls))


if __name__ == "__main__":
    unittest.main()
