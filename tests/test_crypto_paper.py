"""Crypto paper bot (Phase 5): fees, stops, sizing, limits, missed decisions, coin flip, restart. No network."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crypto_paper import brain, market  # noqa: E402
from crypto_paper import rules as R  # noqa: E402
from crypto_paper.book import Book  # noqa: E402
from crypto_paper.runner import Paper  # noqa: E402


def px(btc_bid, btc_ask, eth_bid=3000.0, eth_ask=3000.5):
    return {"BTCUSDT": {"bid": btc_bid, "ask": btc_ask}, "ETHUSDT": {"bid": eth_bid, "ask": eth_ask}}


class FakeMarket:
    @staticmethod
    def snapshot(sym, mid):
        return {"symbol": sym, "price": mid, "atr14_1h": 100.0 if sym == "BTCUSDT" else 5.0, "funding_rate_pct": 0.01,
                "vs_ema20_1h_pct": 0.5, "ema20_vs_ema50_1h_pct": 0.2 if sym == "BTCUSDT" else -0.2}

    @staticmethod
    def funding_rate(sym):
        return 0.0001

    trend_rule = staticmethod(market.trend_rule)


class TestBook(unittest.TestCase):
    def test_long_round_trip_pays_spread_and_fees(self) -> None:
        b = Book("t")
        p = px(60000, 60010)
        b.open("BTCUSDT", "LONG", p, atr=1000, at="t0", reason="r", funding_ok=True)
        pos = b.positions["BTCUSDT"]
        self.assertEqual(pos["entry"], 60010)                                    # bought at the ask
        self.assertAlmostEqual(pos["qty"], R.START_BALANCE * R.RISK_PER_TRADE / (R.STOP_ATR * 1000))
        self.assertAlmostEqual(pos["stop"], 60010 - 1500)
        self.assertAlmostEqual(pos["target"], 60010 + 2500)
        t = b.close("BTCUSDT", p, "t1", "test")                                  # sold at the bid
        expected = pos["qty"] * (60000 - 60010) - pos["qty"] * 60010 * R.TAKER_FEE - pos["qty"] * 60000 * R.TAKER_FEE
        self.assertAlmostEqual(t["pnl"], expected, places=6)
        self.assertLess(b.cash, R.START_BALANCE)

    def test_stop_and_target(self) -> None:
        b = Book("t")
        b.open("BTCUSDT", "SHORT", px(60000, 60010), 100, "t0", "r", True)
        self.assertEqual(b.check_exits(px(60100, 60110), "t1"), [])
        out = b.check_exits(px(60140, 60151), "t2")                              # ask >= 60000+150
        self.assertEqual(out[0]["why"], "stop")
        b.open("ETHUSDT", "LONG", px(60000, 60010), 5, "t3", "r", True)
        out = b.check_exits(px(60000, 60010, 3013, 3013.5), "t4")              # bid >= 3000.5+12.5
        self.assertEqual(out[0]["why"], "target")

    def test_size_caps(self) -> None:
        b = Book("t", spec=R.spec(one_bet=False))     # two longs at once, so the total cap is what is being tested
        b.open("BTCUSDT", "LONG", px(60000, 60000), atr=0.5, at="t", reason="r", funding_ok=True)   # tiny ATR -> huge size wanted
        notional = b.positions["BTCUSDT"]["qty"] * 60000
        self.assertLessEqual(notional, R.START_BALANCE * R.MAX_NOTIONAL_PER_POSITION + 1)
        b.open("ETHUSDT", "LONG", px(60000, 60000), atr=0.01, at="t", reason="r", funding_ok=True)
        self.assertLessEqual(b.gross(px(60000, 60000)), b.equity(px(60000, 60000)) * R.MAX_GROSS_LEVERAGE + 1)

    def test_daily_loss_stop_closes_and_locks(self) -> None:
        b = Book("t")
        b.new_day("d1", px(60000, 60000))
        b.open("BTCUSDT", "LONG", px(60000, 60000), atr=0.5, at="t", reason="r", funding_ok=True)
        msg = b.check_daily_stop(px(57000, 57000), "t2")
        self.assertIsNotNone(msg)
        self.assertEqual(b.positions, {})
        self.assertIsNone(b.open("BTCUSDT", "LONG", px(57000, 57000), 100, "t3", "r", True))
        b.new_day("d2", px(57000, 57000))
        self.assertIsNotNone(b.open("BTCUSDT", "LONG", px(57000, 57000), 100, "t4", "r", True))

    def test_funding_long_pays_positive_rate(self) -> None:
        b = Book("t")
        b.open("BTCUSDT", "LONG", px(60000, 60000), 100, "t", "r", True)
        before = b.cash
        b.apply_funding("BTCUSDT", 0.0001, px(60000, 60000))
        self.assertLess(b.cash, before)
        b.apply_funding("BTCUSDT", None, px(60000, 60000))
        self.assertFalse(b.positions["BTCUSDT"]["funding_known"])


class TestActions(unittest.TestCase):
    def test_wait_keeps_close_exits_reverse_flips(self) -> None:
        b, p = Book("t"), px(60000, 60010)
        b.act("BTCUSDT", "LONG", p, 100, "t0", "r", True)
        self.assertEqual(b.act("BTCUSDT", "WAIT", p, 100, "t1", "r", True), [])
        self.assertIn("BTCUSDT", b.positions)
        self.assertEqual(b.act("BTCUSDT", "LONG", p, 100, "t2", "r", True), [])     # same side = keep, no new fee
        notes = b.act("BTCUSDT", "SHORT", p, 100, "t3", "r", True)
        self.assertEqual(b.positions["BTCUSDT"]["side"], "SHORT")
        self.assertEqual(len(notes), 2)
        self.assertEqual(b.trades[-1]["why"], "reversed to SHORT")
        b.act("BTCUSDT", "CLOSE", p, 100, "t4", "r", True)
        self.assertEqual(b.positions, {})
        self.assertEqual(b.trades[-1]["why"], "closed by decision")
        self.assertEqual(b.act("BTCUSDT", "CLOSE", p, 100, "t5", "r", True), [])    # nothing open: nothing happens

    def test_baselines_only_enter_when_flat(self) -> None:
        b, p = Book("t"), px(60000, 60010)
        self.assertEqual(len(b.enter_if_flat("BTCUSDT", "LONG", p, 100, "t0", "r", True)), 1)
        self.assertEqual(b.enter_if_flat("BTCUSDT", "SHORT", p, 100, "t1", "r", True), [])
        self.assertEqual(b.positions["BTCUSDT"]["side"], "LONG")
        self.assertEqual(b.enter_if_flat("ETHUSDT", None, p, 5, "t2", "r", True), [])

    def test_trend_rule(self) -> None:
        self.assertEqual(market.trend_rule({"vs_ema20_1h_pct": 0.3, "ema20_vs_ema50_1h_pct": 0.1}), "LONG")
        self.assertEqual(market.trend_rule({"vs_ema20_1h_pct": -0.3, "ema20_vs_ema50_1h_pct": -0.1}), "SHORT")
        self.assertIsNone(market.trend_rule({"vs_ema20_1h_pct": 0.3, "ema20_vs_ema50_1h_pct": -0.1}))

    def test_snapshot_from_candles(self) -> None:
        mk = lambda n, step: [{"t": i, "o": 100 + i * step, "h": 101 + i * step, "l": 99 + i * step, "c": 100 + i * step, "v": 10.0}
                              for i in range(n)]
        snap = market.build_snapshot("BTCUSDT", 200.0, mk(39, 1), mk(79, 1), mk(79, 4), 0.0001)
        self.assertEqual(len(snap["last_8_closes_1h"]), 8)
        self.assertGreater(snap["ema20_vs_ema50_1h_pct"], 0)                      # steady rise -> EMA20 above EMA50
        self.assertEqual(snap["funding_rate_pct"], 0.01)
        self.assertGreater(snap["atr14_1h"], 0)
        self.assertEqual(market.trend_rule(snap), "LONG")


class TestBrain(unittest.TestCase):
    def test_parse_strict(self) -> None:
        ok = json.dumps({"decisions": [{"symbol": "BTCUSDT", "action": "LONG", "play": "TREND", "confidence": 2, "reason": "x"},
                                       {"symbol": "ETHUSDT", "action": "WAIT", "play": "NONE", "confidence": 0.1, "reason": "y"}]})
        got = brain.parse(ok)
        self.assertEqual(got["BTCUSDT"]["action"], "LONG")
        self.assertEqual(got["BTCUSDT"]["confidence"], 1.0)
        self.assertIsNone(brain.parse('{"decisions":[{"symbol":"BTCUSDT","action":"LONG"}]}'))   # ETH missing
        self.assertIsNone(brain.parse("BUY BTC NOW"))
        old = json.dumps({"decisions": [{"symbol": "BTCUSDT", "action": "FLAT"}, {"symbol": "ETHUSDT", "action": "CLOSE"}]})
        self.assertIsNone(brain.parse(old))                                       # FLAT no longer exists (v3)
        self.assertIsNone(brain.parse('{"decisions":[{"symbol":"BTCUSDT","action":"YOLO"},{"symbol":"ETHUSDT","action":"FLAT"}]}'))


class TestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_missed_flip_and_restart(self) -> None:
        go = {"BTCUSDT": {"action": "LONG", "play": "TREND", "confidence": .6, "reason": "up"},
              "ETHUSDT": {"action": "WAIT", "play": "NONE", "confidence": .2, "reason": "wait"}}
        wait = {"BTCUSDT": dict(go["BTCUSDT"], action="WAIT"), "ETHUSDT": go["ETHUSDT"]}
        answers = [None, None, go, go, wait, wait]                                # two Qwen calls per round
        seen, seen_pos = [], []
        def fake_decide(snaps, pos, track_record=None, **kw):
            seen.append(track_record)
            seen_pos.append(pos)
            a = answers.pop(0)
            return (a, {"seconds": 0.5}) if a else (None, {"seconds": 60, "error": "timeout"})
        p = Paper(self.tmp, decide=fake_decide, mkt=FakeMarket)
        prices = px(60000, 60010)
        p.tick(prices)
        p.decision_round(prices)
        self.assertEqual(p.meta["missed"], 1)
        self.assertEqual(p.meta["journal_brain"]["missed"], 1)
        p.decision_round(prices)
        self.assertIn("BTCUSDT", p.qwen.positions)
        self.assertIn("BTCUSDT", p.journal.positions)
        self.assertEqual(p.journal.positions["BTCUSDT"]["play"], "TREND")
        self.assertIsNone(seen[0])                                                # plain Qwen never sees a track record
        self.assertIsInstance(seen[1], dict)                                      # the journal one always does
        p.decision_round(prices)                                                  # WAIT keeps the trade open (v3 fix)
        self.assertIn("BTCUSDT", p.qwen.positions)
        self.assertEqual(seen_pos[-1]["BTCUSDT"]["side"], "LONG")                 # Qwen is told its stop and target
        self.assertIn("stop", seen_pos[-1]["BTCUSDT"])
        self.assertIn("BTCUSDT", p.trend.positions)                               # trend rule: BTC up -> LONG
        self.assertEqual(p.trend.positions["BTCUSDT"]["side"], "LONG")
        self.assertNotIn("ETHUSDT", p.trend.positions)                            # ETH signals disagree -> trend rule stays out
        self.assertEqual(len(p.curve), 3)
        self.assertIn("journal", p.curve[-1])
        self.assertIn("trend", p.curve[-1])
        p.save(prices)
        state = json.loads((self.tmp / "state.json").read_text())
        self.assertEqual(state["decisions"], 3)
        self.assertEqual(state["missed"], 1)
        self.assertEqual(state["hold_btc"], R.START_BALANCE)
        self.assertEqual(state["qwen_journal"]["name"], "Qwen + journal")
        self.assertEqual(state["scorecard"]["closed_trades"], 0)
        again = Paper(self.tmp, decide=fake_decide, mkt=FakeMarket)                 # restart carries on
        self.assertIn("BTCUSDT", again.qwen.positions)
        self.assertIn("BTCUSDT", again.journal.positions)
        self.assertEqual(again.meta["decisions"], 3)
        self.assertEqual(state["trend_rule"]["name"], "Trend rule")
        self.assertIn("200", state["pass_bar"])

    def test_old_rules_record_is_archived_not_mixed(self) -> None:
        (self.tmp / "books.json").write_text(json.dumps({"meta": {"rules_version": "v2 · 2026-11-26"}}))
        p = Paper(self.tmp, decide=lambda *a, **k: (None, {}), mkt=FakeMarket)
        self.assertEqual(p.meta["decisions"], 0)
        self.assertEqual(len(list(self.tmp.glob("books_*_old_rules.json"))), 1)


class TestScorecard(unittest.TestCase):
    @staticmethod
    def trade(pnl, side="LONG", play="TREND", why="stop", conf=0.6):
        return {"symbol": "BTCUSDT", "side": side, "play": play, "why": why, "confidence": conf,
                "qty": 1.0, "entry": 1000.0, "pnl": pnl}

    def test_no_numbers_below_min_sample(self) -> None:
        from crypto_paper import scorecard
        card = scorecard.build([self.trade(5)] * (R.MIN_SAMPLE - 1))
        self.assertNotIn("win_rate_pct", card["all"])
        self.assertNotIn("win_rate_pct", card["by_side"]["LONG"])
        self.assertIn("too few", card["all"]["note"])

    def test_numbers_at_min_sample(self) -> None:
        from crypto_paper import scorecard
        trades = [self.trade(10)] * 10 + [self.trade(-5)] * (R.MIN_SAMPLE - 10) + [self.trade(1, side="SHORT", play="FADE", why="target")]
        card = scorecard.build(trades)
        longs = card["by_side"]["LONG"]
        self.assertEqual(longs["trades"], R.MIN_SAMPLE)
        self.assertAlmostEqual(longs["win_rate_pct"], round(10 / R.MIN_SAMPLE * 100, 1))
        self.assertAlmostEqual(longs["total_usd"], 10 * 10 - 5 * (R.MIN_SAMPLE - 10))
        self.assertNotIn("win_rate_pct", card["by_side"]["SHORT"])            # 1 short = luck, no numbers
        self.assertIn("target", card["by_exit"])

    def test_closed_trade_keeps_play_and_confidence(self) -> None:
        b = Book("t")
        b.act("BTCUSDT", "LONG", px(60000, 60010), 100, "t0", "r", True, "FADE", 0.8)
        t = b.close("BTCUSDT", px(60000, 60010), "t1", "test")
        self.assertEqual((t["play"], t["confidence"]), ("FADE", 0.8))


class TestControls(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = []
        def dec(snaps, pos, track_record=None, **kw):
            self.calls.append(track_record is not None)
            return ({s: {"action": "LONG", "play": "TREND", "confidence": .7, "reason": "r"} for s in R.SYMBOLS}, {"seconds": 1})
        self.p = Paper(self.tmp, decide=dec, mkt=FakeMarket)
        self.prices = px(60000, 60010)
        self.p.tick(self.prices)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self, action, account):
        from crypto_paper import controls
        controls.send(self.tmp, action, account)
        for path, cmd in controls.pending(self.tmp):
            self.p.apply(cmd, self.prices)
            controls.file_done(path)

    def test_send_refuses_unknown_values(self) -> None:
        from crypto_paper import controls
        with self.assertRaises(ValueError):
            controls.send(self.tmp, "withdraw", "qwen")
        with self.assertRaises(ValueError):
            controls.send(self.tmp, "reset", "binance")

    def test_pause_stops_new_trades_and_skips_qwen(self) -> None:
        self.run_cmd("pause", "qwen")
        self.p.decision_round(self.prices)
        self.assertEqual(self.p.qwen.positions, {})
        self.assertEqual(self.calls, [True])                       # only the journal Qwen was asked
        self.assertIn("BTCUSDT", self.p.journal.positions)
        self.run_cmd("resume", "qwen")
        self.p.decision_round(self.prices)
        self.assertIn("BTCUSDT", self.p.qwen.positions)

    def test_close_trades_and_reset_archive_never_delete(self) -> None:
        self.p.decision_round(self.prices)
        self.run_cmd("close_trades", "journal")
        self.assertEqual(self.p.journal.positions, {})
        self.assertTrue(all(t["why"] == "closed by Markus" for t in self.p.journal.trades))
        self.assertIn("BTCUSDT", self.p.qwen.positions)             # other accounts untouched
        old_trades = len(self.p.journal.trades)
        self.run_cmd("reset", "journal")
        self.assertEqual(self.p.journal.trades, [])
        self.assertEqual(self.p.journal.cash, R.START_BALANCE)
        archived = json.loads(next((self.tmp / "archive").glob("journal_*.json")).read_text())
        self.assertEqual(len(archived["trades"]), old_trades)
        self.assertEqual(len(list((self.tmp / "inbox" / "done").glob("*.json"))), 2)   # commands filed, not deleted

    def test_reset_all_and_restart_keeps_reset(self) -> None:
        self.p.decision_round(self.prices)
        self.p.save(self.prices)
        self.run_cmd("reset", "all")
        self.assertEqual(self.p.meta["decisions"], 0)
        self.assertEqual(self.p.qwen.positions, {})
        self.assertTrue(list((self.tmp / "archive").glob("books_*.json")))
        self.p.save(self.prices)
        again = Paper(self.tmp, decide=lambda *a, **k: (None, {}), mkt=FakeMarket)
        self.assertEqual(again.meta["decisions"], 0)

    def test_old_command_is_ignored(self) -> None:
        self.p.decision_round(self.prices)
        self.p.apply({"action": "close_trades", "account": "all", "at": 0}, self.prices)
        self.assertIn("BTCUSDT", self.p.qwen.positions)

    def test_decide_now(self) -> None:
        self.p.meta["last_decision_slot"] = 123
        self.run_cmd("decide_now", "qwen")
        self.assertEqual(self.p.meta["last_decision_slot"], 0)


class TestSingleInstance(unittest.TestCase):
    def test_second_copy_cannot_lock_and_reset_archives(self) -> None:
        import crypto_paper.runner as run
        tmp = Path(tempfile.mkdtemp())
        old = run.DATA
        run.DATA = tmp
        try:
            first = run._single_instance_lock()
            self.assertIsNotNone(first)
            import subprocess
            code = ("import sys,crypto_paper.runner as r;from pathlib import Path;r.DATA=Path(sys.argv[1]);"
                    "print('LOCKED' if r._single_instance_lock() is None else 'GOT')")
            out = subprocess.run([sys.executable, "-c", code, str(tmp)], capture_output=True, text=True,
                                 cwd=str(Path(__file__).resolve().parent.parent)).stdout.strip()
            self.assertEqual(out, "LOCKED")
            (tmp / "books.json").write_text("{}")
            (tmp / "RESET").write_text("")
            run._reset_if_asked()
            self.assertFalse((tmp / "books.json").exists())
            self.assertFalse((tmp / "RESET").exists())
            self.assertEqual(len(list(tmp.glob("books_reset_*.json"))), 1)
            first.close()
        finally:
            run.DATA = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
