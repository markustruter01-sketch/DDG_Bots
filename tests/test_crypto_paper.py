"""Crypto paper bot (Phase 5): fees, stops, sizing, limits, missed decisions, coin flip, restart. No network."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crypto_paper import brain  # noqa: E402
from crypto_paper import rules as R  # noqa: E402
from crypto_paper.book import Book  # noqa: E402
from crypto_paper.runner import Paper  # noqa: E402


def px(btc_bid, btc_ask, eth_bid=3000.0, eth_ask=3000.5):
    return {"BTCUSDT": {"bid": btc_bid, "ask": btc_ask}, "ETHUSDT": {"bid": eth_bid, "ask": eth_ask}}


class FakeMarket:
    @staticmethod
    def snapshot(sym, mid):
        return {"symbol": sym, "price": mid, "atr14_5m": 100.0 if sym == "BTCUSDT" else 5.0}

    @staticmethod
    def funding_rate(sym):
        return 0.0001


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
        b = Book("t")
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


class TestBrain(unittest.TestCase):
    def test_parse_strict(self) -> None:
        ok = json.dumps({"decisions": [{"symbol": "BTCUSDT", "action": "LONG", "play": "TREND", "confidence": 2, "reason": "x"},
                                       {"symbol": "ETHUSDT", "action": "FLAT", "play": "NONE", "confidence": 0.1, "reason": "y"}]})
        got = brain.parse(ok)
        self.assertEqual(got["BTCUSDT"]["action"], "LONG")
        self.assertEqual(got["BTCUSDT"]["confidence"], 1.0)
        self.assertIsNone(brain.parse('{"decisions":[{"symbol":"BTCUSDT","action":"LONG"}]}'))   # ETH missing
        self.assertIsNone(brain.parse("BUY BTC NOW"))
        self.assertIsNone(brain.parse('{"decisions":[{"symbol":"BTCUSDT","action":"YOLO"},{"symbol":"ETHUSDT","action":"FLAT"}]}'))


class TestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_missed_flip_and_restart(self) -> None:
        answers = [None, {"BTCUSDT": {"action": "LONG", "play": "TREND", "confidence": .6, "reason": "up"},
                          "ETHUSDT": {"action": "FLAT", "play": "NONE", "confidence": .2, "reason": "flat"}}]
        def fake_decide(snaps, pos):
            a = answers.pop(0)
            return (a, {"seconds": 0.5}) if a else (None, {"seconds": 60, "error": "timeout"})
        p = Paper(self.tmp, decide=fake_decide, mkt=FakeMarket)
        prices = px(60000, 60010)
        p.tick(prices)
        p.decision_round(prices)
        self.assertEqual(p.meta["missed"], 1)
        p.decision_round(prices)
        self.assertIn("BTCUSDT", p.qwen.positions)
        self.assertEqual(len(p.curve), 2)
        p.save(prices)
        state = json.loads((self.tmp / "state.json").read_text())
        self.assertEqual(state["decisions"], 2)
        self.assertEqual(state["missed"], 1)
        self.assertEqual(state["hold_btc"], R.START_BALANCE)
        again = Paper(self.tmp, decide=fake_decide, mkt=FakeMarket)                 # restart carries on
        self.assertIn("BTCUSDT", again.qwen.positions)
        self.assertEqual(again.meta["decisions"], 2)


if __name__ == "__main__":
    unittest.main()
