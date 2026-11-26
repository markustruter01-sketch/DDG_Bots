"""Crypto paper bot, rules v4: cost limits, venues, the veto account, fresh-price fills, coin-flip bank, pinning. No network."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crypto_paper import brain, events, market, scorecard  # noqa: E402
from crypto_paper import rules as R  # noqa: E402
from crypto_paper.book import Book  # noqa: E402
from crypto_paper.runner import Paper  # noqa: E402


def px(btc_bid, btc_ask, eth_bid=3000.0, eth_ask=3000.5):
    return {"BTCUSDT": {"bid": btc_bid, "ask": btc_ask}, "ETHUSDT": {"bid": eth_bid, "ask": eth_ask}}


def at(minute: int) -> str:
    return f"2026-11-27T{10 + minute // 60:02d}:{minute % 60:02d}:00+10:00"


P = px(60000, 60010)


class TestCostLimits(unittest.TestCase):
    def test_cooldown_after_an_exit(self) -> None:
        b = Book("t")
        self.assertIsNotNone(b.open("BTCUSDT", "LONG", P, 100, at(0), "r", True))
        b.close("BTCUSDT", P, at(10), "test")
        self.assertIsNone(b.open("BTCUSDT", "LONG", P, 100, at(10 + R.COOLDOWN_MINUTES - 1), "r", True))
        self.assertIn("cooldown", b.last_refusal)
        self.assertIsNotNone(b.open("ETHUSDT", "LONG", P, 5, at(11), "r", True))       # the other coin is not cooling down
        self.assertIsNotNone(b.open("BTCUSDT", "SHORT", P, 100, at(10 + R.COOLDOWN_MINUTES), "r", True))

    def test_a_reversal_closes_but_cannot_reopen_during_the_cooldown(self) -> None:
        b = Book("t")
        b.act("BTCUSDT", "LONG", P, 100, at(0), "r", True)
        notes = b.act("BTCUSDT", "SHORT", P, 100, at(15), "r", True)
        self.assertEqual(b.positions, {})
        self.assertTrue(any("not opened" in n and "cooldown" in n for n in notes))

    def test_entry_limit_per_day_resets_next_day(self) -> None:
        b = Book("t", spec=R.spec(cooldown_min=0))
        b.new_day("d1", P)
        for i in range(R.MAX_ENTRIES_PER_DAY):
            self.assertIsNotNone(b.open("BTCUSDT", "LONG", P, 100, at(i), "r", True))
            b.close("BTCUSDT", P, at(i), "test")
        self.assertIsNone(b.open("BTCUSDT", "LONG", P, 100, at(30), "r", True))
        self.assertIn("entry limit", b.last_refusal)
        b.new_day("d2", P)
        self.assertIsNotNone(b.open("BTCUSDT", "LONG", P, 100, at(31), "r", True))

    def test_same_direction_on_both_coins_is_one_bet(self) -> None:
        b = Book("t")
        b.open("BTCUSDT", "LONG", P, 100, at(0), "r", True)
        self.assertIsNone(b.open("ETHUSDT", "LONG", P, 5, at(0), "r", True))
        self.assertIn("one bet", b.last_refusal)
        self.assertIsNotNone(b.open("ETHUSDT", "SHORT", P, 5, at(0), "r", True))       # the opposite side is a different bet

    def test_unknown_setting_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            R.spec(leverage=50)


class TestVenues(unittest.TestCase):
    def test_spot_account_is_long_only_unlevered_and_pays_spot_fees(self) -> None:
        b = Book("spot", spec=R.spec("spot"))
        self.assertIsNone(b.open("BTCUSDT", "SHORT", P, 100, at(0), "r", True))
        self.assertIn("short", b.last_refusal)
        b.open("BTCUSDT", "LONG", P, atr=0.5, at=at(0), reason="r", funding_ok=True)   # tiny ATR -> wants a huge size
        pos = b.positions["BTCUSDT"]
        self.assertLessEqual(pos["qty"] * 60010, R.START_BALANCE + 1)                  # never more than the account holds
        self.assertAlmostEqual(pos["fees"], pos["qty"] * 60010 * 0.008)
        cash = b.cash
        b.apply_funding("BTCUSDT", 0.0001, P)
        self.assertEqual(b.cash, cash)                                                  # spot has no funding

    def test_futures_fee_is_unchanged_from_v3(self) -> None:
        b = Book("t")
        b.open("BTCUSDT", "LONG", P, 1000, at(0), "r", True)
        pos = b.positions["BTCUSDT"]
        self.assertAlmostEqual(pos["fees"], pos["qty"] * 60010 * R.TAKER_FEE)


class TestOptions(unittest.TestCase):
    def test_limit_order_fills_only_when_price_trades_through_and_pays_maker_fee(self) -> None:
        b = Book("t", spec=R.spec(entry="limit"))
        note = b.enter("BTCUSDT", "LONG", P, 100, at(0), "r", True)
        self.assertIn("limit", note)
        self.assertEqual(b.positions, {})
        self.assertEqual(b.check_pending(px(60005, 60015), at(1)), [])                 # ask still above the order
        notes = b.check_pending(px(59990, 60000), at(2))                               # ask came down to 60000
        self.assertIn("filled", notes[0])
        pos = b.positions["BTCUSDT"]
        self.assertEqual(pos["entry"], 60000)
        self.assertAlmostEqual(pos["fees"], pos["qty"] * 60000 * R.MAKER_FEE)

    def test_unfilled_limit_order_is_dropped(self) -> None:
        b = Book("t", spec=R.spec(entry="limit"))
        b.enter("BTCUSDT", "SHORT", P, 100, at(0), "r", True)
        self.assertEqual(b.check_pending(P, at(R.LIMIT_TTL_MINUTES - 1)), [])
        self.assertIn("dropped", b.check_pending(P, at(R.LIMIT_TTL_MINUTES))[0])
        self.assertEqual((b.pending, b.positions, b.entries_today), ({}, {}, 0))

    def test_breakeven_and_trailing_exits(self) -> None:
        be = Book("be", spec=R.spec(exits="breakeven"))
        be.open("BTCUSDT", "LONG", P, 100, at(0), "r", True)                            # entry 60010, stop 59860
        be.check_exits(px(60050, 60060), at(1))
        self.assertAlmostEqual(be.positions["BTCUSDT"]["stop"], 60010 - 150)
        be.check_exits(px(60110, 60120), at(2))                                         # 1 ATR in front
        self.assertEqual(be.positions["BTCUSDT"]["stop"], 60010)
        tr = Book("tr", spec=R.spec(exits="trail"))
        tr.open("BTCUSDT", "LONG", P, 100, at(0), "r", True)
        self.assertIsNone(tr.positions["BTCUSDT"]["target"])
        tr.check_exits(px(60400, 60410), at(1))
        self.assertAlmostEqual(tr.positions["BTCUSDT"]["stop"], 60400 - 150)
        self.assertEqual(tr.check_exits(px(60240, 60250), at(2))[0]["why"], "stop")

    def test_replay_candle_stop_counts_before_target_and_gaps_fill_at_the_open(self) -> None:
        b = Book("t")
        b.open("BTCUSDT", "LONG", px(60000, 60000), 100, at(0), "r", True)            # stop 59850, target 60250
        t = b.exit_on_bar("BTCUSDT", o=60000, h=60300, low=59800, half_spread=0, prices=P, at=at(1))
        self.assertEqual((t["why"], t["exit"]), ("stop", 59850))
        b2 = Book("t2")
        b2.open("BTCUSDT", "LONG", px(60000, 60000), 100, at(0), "r", True)
        t2 = b2.exit_on_bar("BTCUSDT", o=59700, h=59750, low=59600, half_spread=0, prices=P, at=at(1))
        self.assertEqual(t2["exit"], 59700)                                             # opened below the stop: no better fill


class TestEvents(unittest.TestCase):
    def test_calendar_loads_and_blackout_window(self) -> None:
        cal = events.load()
        self.assertGreater(len(cal), 20)
        fomc = datetime(2026, 12, 9, 19, 0, tzinfo=timezone.utc)
        self.assertIn("FOMC", events.in_blackout(fomc, cal))
        self.assertIsNotNone(events.in_blackout(datetime(2026, 12, 9, 18, 31, tzinfo=timezone.utc), cal))
        self.assertIsNone(events.in_blackout(datetime(2026, 12, 9, 18, 29, tzinfo=timezone.utc), cal))
        self.assertEqual(events.load(Path("no-such-file.json")), [])


class TestVetoBrain(unittest.TestCase):
    CARDS = [{"symbol": "BTCUSDT", "side": "LONG", "facts": {"x": 1}}]

    @staticmethod
    def answers(seq):
        seq = list(seq)
        def ask(system, user, schema, model, think, sample):
            a = seq.pop(0)
            if a is None:
                return None, {"seconds": 1.0, "error": "timeout"}
            return json.dumps({"verdicts": [{"symbol": "BTCUSDT", "verdict": a, "reason": a.lower()}]}), {"seconds": 1.0}
        ask.left = seq
        return ask

    def test_parse_is_strict(self) -> None:
        ok = '{"verdicts":[{"symbol":"BTCUSDT","verdict":"TAKE","reason":"x"}]}'
        self.assertEqual(brain.parse_veto(ok, ["BTCUSDT"])["BTCUSDT"]["verdict"], "TAKE")
        self.assertIsNone(brain.parse_veto(ok, ["BTCUSDT", "ETHUSDT"]))                # a proposal left unanswered
        self.assertIsNone(brain.parse_veto('{"verdicts":[{"symbol":"BTCUSDT","verdict":"MAYBE"}]}', ["BTCUSDT"]))
        self.assertIsNone(brain.parse_veto("TAKE IT", ["BTCUSDT"]))

    def test_four_of_five_takes_three_does_not(self) -> None:
        got, info = brain.veto(self.CARDS, ask=self.answers(["TAKE", "TAKE", "SKIP", "TAKE", "TAKE"]))
        self.assertTrue(got["BTCUSDT"]["take"])
        self.assertEqual(got["BTCUSDT"]["votes_take"], 4)
        got, _ = brain.veto(self.CARDS, ask=self.answers(["TAKE", "SKIP", "TAKE", "SKIP", "TAKE"]))
        self.assertFalse(got["BTCUSDT"]["take"])

    def test_stops_asking_once_decided(self) -> None:
        ask = self.answers(["SKIP", "SKIP", "TAKE", "TAKE", "TAKE"])
        got, info = brain.veto(self.CARDS, ask=ask)
        self.assertFalse(got["BTCUSDT"]["take"])
        self.assertEqual(info["asked"], 2)                                              # two SKIPs: four TAKEs are out of reach

    def test_silence_never_opens_a_trade(self) -> None:
        got, _ = brain.veto(self.CARDS, ask=self.answers(["TAKE", None, "TAKE", "TAKE", None]))
        self.assertFalse(got["BTCUSDT"]["take"])                                        # only 3 real TAKEs
        got, info = brain.veto(self.CARDS, ask=self.answers([None] * 5))
        self.assertIsNone(got)                                                          # nothing usable = a missed decision
        self.assertIn("error", info)
        got, info = brain.veto(self.CARDS, budget_s=-1, ask=self.answers(["TAKE"] * 5))
        self.assertIsNone(got)                                                          # out of time before any answer

    def test_picker_vote_needs_agreement(self) -> None:
        def ask_for(actions):
            actions = list(actions)
            def ask(system, user, schema, model, think, sample):
                a = actions.pop(0)
                return json.dumps({"decisions": [{"symbol": s, "action": a, "play": "TREND", "confidence": 0.9, "reason": "r"}
                                                 for s in R.SYMBOLS]}), {"seconds": 0.1}
            return ask
        got, _ = brain.decide_vote([], {}, ask=ask_for(["LONG"] * 4 + ["SHORT"]))
        self.assertEqual(got["BTCUSDT"]["action"], "LONG")
        got, _ = brain.decide_vote([], {}, ask=ask_for(["LONG", "LONG", "SHORT", "SHORT", "WAIT"]))
        self.assertEqual(got["BTCUSDT"]["action"], "WAIT")

    def test_prompts_tell_the_truth_about_the_limits(self) -> None:
        self.assertIn(f"{R.COOLDOWN_MINUTES} minutes", brain.SYSTEM)
        self.assertIn(f"{R.MAX_ENTRIES_PER_DAY} new trades", brain.SYSTEM)
        self.assertIn("PAPER-MONEY", brain.VETO_SYSTEM)
        self.assertIn("cannot", brain.VETO_SYSTEM)

    def test_fingerprint_moves_with_prompt_and_rules(self) -> None:
        fp = brain.fingerprint()
        self.assertEqual(fp, brain.fingerprint())
        old = brain.VETO_SYSTEM
        try:
            brain.VETO_SYSTEM = old + " Be bold."
            self.assertNotEqual(fp, brain.fingerprint())
        finally:
            brain.VETO_SYSTEM = old
        old_risk = R.RISK_PER_TRADE
        try:
            R.RISK_PER_TRADE = 0.02
            self.assertNotEqual(fp, brain.fingerprint())
        finally:
            R.RISK_PER_TRADE = old_risk


class FakeMarket:
    """Trend rule says LONG on BTC, nothing on ETH. `book` moves the price after every answer (the model was thinking)."""
    after = None

    @staticmethod
    def snapshot(sym, mid):
        return {"symbol": sym, "price": mid, "atr14_1h": 100.0 if sym == "BTCUSDT" else 5.0, "funding_rate_pct": 0.01,
                "vs_ema20_1h_pct": 0.5, "ema20_vs_ema50_1h_pct": 0.2 if sym == "BTCUSDT" else -0.2}

    @staticmethod
    def funding_rate(sym):
        return 0.0001

    @classmethod
    def book(cls, symbols):
        return cls.after

    trend_rule = staticmethod(market.trend_rule)


class TestRunnerV4(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        FakeMarket.after = px(60100, 60110)
        self.wait = ({s: {"action": "WAIT", "play": "NONE", "confidence": .2, "reason": "wait"} for s in R.SYMBOLS}, {"seconds": 1.0})
        self.seen_cards = []

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def paper(self, decide=None, take=True, digest=None):
        def veto(cards):
            self.seen_cards.append(cards)
            if take is None:
                return None, {"seconds": 45.0, "error": "timeout"}
            return ({c["symbol"]: {"take": take, "votes_take": 5 if take else 1, "votes_skip": 0 if take else 4, "reason": "r"}
                     for c in cards}, {"seconds": 3.0, "votes": 5})
        return Paper(self.tmp, decide=decide or (lambda *a, **k: self.wait), mkt=FakeMarket, veto=veto, digest=digest)

    def test_buttons_reach_the_new_accounts(self) -> None:
        import time as _time
        from crypto_paper import controls, runner
        self.assertEqual(set(controls.ACCOUNTS) - {"all"}, set(runner.ACCOUNTS))        # the dashboard and the bot agree
        p = self.paper(take=True)
        p.tick(P)
        p.apply({"action": "pause", "account": "veto_spot", "at": _time.time()}, P)
        p.decision_round(P)
        self.assertIn("BTCUSDT", p.veto.positions)
        self.assertEqual(p.veto_spot.positions, {})                                    # paused: it sat this one out
        p.apply({"action": "close_trades", "account": "veto", "at": _time.time()}, P)
        self.assertEqual(p.veto.positions, {})
        self.assertIn("BTCUSDT", p.trend.positions)                                    # only the account asked for

    def test_reset_account_is_archived_and_not_ranked_against_older_coin_flips(self) -> None:
        import time as _time
        p = self.paper(take=True)
        p.tick(P)
        p.decision_round(P)
        self.assertIn("trend_veto", p._state(P)["rank_vs_flips"])
        _time.sleep(1.1)                                                               # start times are kept to the second
        p.apply({"action": "reset", "account": "veto", "at": _time.time()}, P)
        self.assertTrue(list((self.tmp / "archive").glob("veto_*.json")))              # nothing is lost
        self.assertEqual(p.veto.positions, {})
        self.assertEqual(p.meta["veto_log"], [])
        ranks = p._state(P)["rank_vs_flips"]
        self.assertNotIn("trend_veto", ranks)                                          # a different period: no rank shown
        self.assertIn("trend_rule", ranks)

    def test_veto_take_follows_the_trend_rule_at_the_later_price(self) -> None:
        p = self.paper(take=True)
        p.tick(P)
        p.decision_round(P)
        self.assertEqual(p.trend.positions["BTCUSDT"]["entry"], 60010)                  # plain code: the round's opening price
        self.assertEqual(p.veto.positions["BTCUSDT"]["entry"], 60110)                   # the model: the price after it answered
        self.assertEqual(p.veto_spot.positions["BTCUSDT"]["side"], "LONG")
        self.assertEqual([c["symbol"] for c in self.seen_cards[0]], ["BTCUSDT"])        # asked only about what the rule opened
        self.assertEqual(self.seen_cards[0][0]["side"], "LONG")
        log = p.meta["veto_log"][-1]
        self.assertTrue(log["take"])
        self.assertEqual(log["trend_opened"], p.trend.positions["BTCUSDT"]["opened"])
        p.decision_round(P)                                                             # trend rule opens nothing new
        self.assertEqual(len(self.seen_cards), 1)                                       # so Qwen is not asked again

    def test_veto_skip_opens_nothing_and_is_recorded(self) -> None:
        p = self.paper(take=False)
        p.tick(P)
        p.decision_round(P)
        self.assertIn("BTCUSDT", p.trend.positions)
        self.assertEqual((p.veto.positions, p.veto_spot.positions), ({}, {}))
        self.assertFalse(p.meta["veto_log"][-1]["take"])
        self.assertEqual(p.meta["veto_brain"]["missed"], 0)

    def test_veto_missed_opens_nothing_and_counts_as_missed(self) -> None:
        p = self.paper(take=None)
        p.tick(P)
        p.decision_round(P)
        self.assertEqual(p.veto.positions, {})
        self.assertEqual(p.meta["veto_brain"]["missed"], 1)
        self.assertIsNone(p.meta["veto_log"][-1]["take"])
        split = scorecard.veto_split(p.meta["veto_log"], p.trend.trades)
        self.assertEqual(split["not_answered"], 1)

    def test_picker_fills_after_the_answer_and_stops_are_checked_meanwhile(self) -> None:
        go = ({"BTCUSDT": {"action": "LONG", "play": "TREND", "confidence": .7, "reason": "up"},
               "ETHUSDT": {"action": "WAIT", "play": "NONE", "confidence": .2, "reason": "w"}}, {"seconds": 2.0})
        p = self.paper(decide=lambda *a, **k: go)
        p.tick(P)
        p.decision_round(P)
        self.assertEqual(p.qwen.positions["BTCUSDT"]["entry"], 60110)                   # not the 60010 it was shown
        FakeMarket.after = px(59000, 59010)                                             # falls through every stop while Qwen thinks
        p.decision_round(P)
        self.assertEqual(p.trend.positions, {})
        self.assertEqual(p.trend.trades[-1]["why"], "stop")

    def test_no_fresh_price_means_missed_not_a_stale_fill(self) -> None:
        go = ({s: {"action": "LONG", "play": "TREND", "confidence": .7, "reason": "up"} for s in R.SYMBOLS}, {"seconds": 2.0})
        p = self.paper(decide=lambda *a, **k: go)
        p.tick(P)
        def down(symbols):
            raise OSError("network down")
        p.mkt = type("M", (FakeMarket,), {"book": staticmethod(down)})
        p.decision_round(P)
        self.assertEqual(p.qwen.positions, {})
        self.assertEqual(p.meta["missed"], 1)

    def test_coin_flip_bank_runs_ranks_and_survives_a_restart(self) -> None:
        p = self.paper()
        p.tick(P)
        for _ in range(3):
            p.decision_round(P)
        self.assertEqual(len(p.bank), R.FLIP_BANK)
        in_trade = sum(1 for b in p.bank if b.positions)
        self.assertGreater(in_trade, R.FLIP_BANK // 2)
        self.assertLess(len({json.dumps(sorted((s, q["side"]) for s, q in b.positions.items())) for b in p.bank}), R.FLIP_BANK)
        self.assertGreater(len({json.dumps(sorted((s, q["side"]) for s, q in b.positions.items())) for b in p.bank}), 3)
        p.save(FakeMarket.after)
        st = json.loads((self.tmp / "state.json").read_text())
        self.assertEqual(st["coin_flips"]["n"], R.FLIP_BANK)
        self.assertEqual(st["rank_vs_flips"]["trend_rule"]["of"], R.FLIP_BANK)
        self.assertEqual([a["key"] for a in st["accounts"]], ["qwen", "journal", "veto", "veto_spot", "trend", "flip"])
        self.assertEqual(st["trend_veto"]["name"], "Trend + Qwen veto")
        self.assertEqual(st["veto_spot"]["venue"], "spot")
        self.assertIn("cooldown", st["limits"])
        again = self.paper()
        self.assertEqual(sum(1 for b in again.bank if b.positions), in_trade)
        self.assertIn("BTCUSDT", again.veto.positions)
        self.assertEqual(again.veto.spec["venue"], "futures")
        self.assertEqual(again.veto_spot.spec["taker_fee"], 0.008)                      # settings come from the code, not the file

    def test_everything_shown_to_qwen_is_kept(self) -> None:
        p = self.paper()
        p.tick(P)
        p.decision_round(P)
        row = json.loads((self.tmp / "decisions.jsonl").read_text().splitlines()[0])
        self.assertEqual(row["round"], 1)
        self.assertEqual(len(row["market"]), 2)
        self.assertIn("veto", row)
        self.assertIn("Qwen", row)

    def test_changed_model_file_when_nothing_rechecks_prices_mid_round(self) -> None:
        # No order book on this market, so no model account re-checks prices mid-round (as when both Qwen accounts are paused).
        quiet_market = type("M", (), {"snapshot": FakeMarket.snapshot, "funding_rate": FakeMarket.funding_rate,
                                      "trend_rule": FakeMarket.trend_rule})
        ids = ["sha256:aaa"]
        p = Paper(self.tmp, decide=lambda *a, **k: self.wait, mkt=quiet_market, digest=lambda: ids[0])
        p.tick(P)
        p.meta["last_decision_slot"] = 777
        p.decision_round(P)
        ids[0] = "sha256:bbb"
        p.decision_round(P)                                                             # must not fail on the fresh accounts
        self.assertEqual(p.meta["decisions"], 1)
        self.assertEqual(p.meta["last_decision_slot"], 777)                             # no second round in the same 15 minutes
        self.assertIsNotNone(p.meta["hold_btc_start"])
        self.assertTrue(p.trend.day)

    def test_changed_model_file_starts_a_fresh_record(self) -> None:
        ids = ["sha256:aaa"]
        p = self.paper(digest=lambda: ids[0])
        p.tick(P)
        p.decision_round(P)
        p.decision_round(P)
        self.assertEqual(p.meta["model_digest"], "sha256:aaa")
        self.assertEqual(p.meta["decisions"], 2)
        ids[0] = "sha256:bbb"
        p.tick(P)
        p.decision_round(P)
        self.assertEqual(p.meta["decisions"], 1)                                        # fresh record, this is its first round
        self.assertEqual(p.meta["model_digest"], "sha256:bbb")
        self.assertTrue(list((self.tmp / "archive").glob("all_*.json")))
        ids[0] = None                                                                   # Ollama not answering is not a change
        p.decision_round(P)
        self.assertEqual(p.meta["decisions"], 2)

    def test_changed_prompt_archives_the_old_record_on_start(self) -> None:
        p = self.paper()
        p.tick(P)
        p.decision_round(P)
        p.save(P)
        old = brain.SYSTEM
        try:
            brain.SYSTEM = old + " Trade more."
            again = self.paper()
            self.assertEqual(again.meta["decisions"], 0)
            self.assertEqual(len(list(self.tmp.glob("books_*_old_rules.json"))), 1)
            self.assertEqual(len(list(self.tmp.glob("flip_bank_*_old_rules.json"))), 1)
        finally:
            brain.SYSTEM = old

    def test_funding_is_charged_once_and_flagged_when_missed(self) -> None:
        p = self.paper()
        p.tick(P)
        p.decision_round(P)                                                             # trend holds BTC LONG
        utc = lambda h, m: datetime(2026, 11, 27, h, m, tzinfo=timezone.utc)
        p.meta["last_funding_slot"] = ""
        p._funding(P, utc(7, 59))
        self.assertEqual(p.trend.funding, 0.0)                                          # first sight of a slot: nothing owed yet
        p._funding(P, utc(8, 1))
        charged = p.trend.funding
        self.assertGreater(charged, 0)                                                  # long pays a positive rate
        p._funding(P, utc(8, 2))
        self.assertEqual(p.trend.funding, charged)                                      # once per funding time
        p._funding(P, utc(16, 30))                                                      # the bot "was off" at 16:00
        self.assertEqual(p.trend.funding, charged)
        self.assertEqual(p.meta["funding_skipped"], 1)
        self.assertFalse(p.trend.positions["BTCUSDT"]["funding_known"])


class TestScorecardV4(unittest.TestCase):
    def test_veto_split_uses_the_trend_rules_own_results(self) -> None:
        trades = [{"symbol": "BTCUSDT", "opened": f"t{i}", "qty": 1.0, "entry": 1000.0, "pnl": 10.0 if i % 2 else -10.0}
                  for i in range(2 * R.MIN_SAMPLE)]
        log = [{"symbol": "BTCUSDT", "trend_opened": f"t{i}", "take": bool(i % 2)} for i in range(2 * R.MIN_SAMPLE)]
        log.append({"symbol": "BTCUSDT", "trend_opened": "still-open", "take": True})
        split = scorecard.veto_split(log, trades)
        self.assertEqual(split["taken"]["win_rate_pct"], 100.0)                         # it took every winner
        self.assertEqual(split["skipped"]["win_rate_pct"], 0.0)                         # and skipped every loser
        self.assertEqual(split["still_open_or_unknown"], 1)

    def test_rank_and_spread(self) -> None:
        flips = [float(x) for x in range(100, 300)]
        self.assertEqual(scorecard.rank_among(250.5, flips), {"beats": 151, "of": 200})
        s = scorecard.spread(flips)
        self.assertEqual((s["n"], s["worst"], s["best"]), (200, 100.0, 299.0))
        self.assertLess(s["p5"], s["median"])
        self.assertEqual(scorecard.spread([]), {"n": 0})


class TestFacts(unittest.TestCase):
    def test_facts_are_labels_and_atr_distances(self) -> None:
        mk = lambda n, step: [{"t": i, "o": 100 + i * step, "h": 101 + i * step, "l": 99 + i * step, "c": 100 + i * step, "v": 10.0}
                              for i in range(n)]
        h1 = mk(749, 0.2)
        f = market.build_facts("BTCUSDT", h1[-1]["c"] + 1, h1, mk(79, 0.8), 0.0006, hour_utc=14)
        self.assertEqual(f["trend_1h"]["direction"], "up")
        self.assertIn(f["trend_1h"]["label"], ("weak", "moderate", "strong"))
        self.assertEqual(f["range_24h"]["label"], "near the high")
        self.assertEqual(f["funding"]["label"], "extreme, longs pay")
        self.assertEqual(f["session_utc"], "US")
        self.assertIsNotNone(f["volatility"]["percentile_30d"])
        self.assertNotIn("last_8_closes_1h", f)                                         # no raw price list to do sums on

    def test_snapshot_numbers_do_not_change_with_the_longer_history(self) -> None:
        mk = lambda n: [{"t": i, "o": 100 + (i % 7), "h": 103 + (i % 7), "l": 98 + (i % 5), "c": 100 + (i % 11), "v": 10.0 + i % 3}
                        for i in range(n)]
        long_h1 = mk(749)
        self.assertEqual(market.build_snapshot("BTCUSDT", 105.0, mk(39), long_h1[-79:], mk(79), 0.0001),
                         market.build_snapshot("BTCUSDT", 105.0, mk(39), long_h1[-(market.H1_FOR_SNAPSHOT - 1):], mk(79), 0.0001))
        series = market.atr_series(long_h1)
        self.assertAlmostEqual(series[-1], market.atr(long_h1), places=9)


class TestSharedModelSettings(unittest.TestCase):
    def test_studio_chat_and_crypto_bot_use_one_context_size(self) -> None:
        from studio.ai_director import OllamaClient
        self.assertEqual(OllamaClient().num_ctx, R.NUM_CTX)                             # a different size makes Ollama reload the model


if __name__ == "__main__":
    unittest.main()


class FakeOllama:
    """A stand-in for Ollama on a local port, so the real request code runs without the real model."""

    def __init__(self, answers, prompt_tokens=900):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.answers, self.seen, outer = list(answers), [], self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                raw = json.dumps(obj).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._send({"models": [{"name": R.MODEL, "model": R.MODEL, "digest": "sha256:feedbeef"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                outer.seen.append(body)
                text = outer.answers.pop(0) if outer.answers else "{}"
                self._send({"message": {"content": text}, "eval_count": 40, "prompt_eval_count": prompt_tokens})

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class TestRealRequestPath(unittest.TestCase):
    """brain.py talking HTTP to a stand-in server: the request Ollama gets and what the bot makes of the reply."""

    def test_picker_request_and_answer(self) -> None:
        good = json.dumps({"decisions": [{"symbol": s, "action": "WAIT", "play": "NONE", "confidence": 0.4, "reason": "r"}
                                         for s in R.SYMBOLS]})
        o = FakeOllama([good])
        try:
            got, info = brain.decide([{"symbol": s} for s in R.SYMBOLS], {}, o.url)
            self.assertEqual(brain.model_digest(o.url), "sha256:feedbeef")
        finally:
            o.close()
        self.assertEqual(got["BTCUSDT"]["action"], "WAIT")
        self.assertNotIn("error", info)
        req = o.seen[0]
        self.assertEqual((req["model"], req["stream"], req["think"]), (R.MODEL, False, False))
        self.assertEqual(req["options"]["num_ctx"], R.NUM_CTX)
        self.assertEqual(req["keep_alive"], R.KEEP_ALIVE)
        self.assertEqual(req["format"], brain.SCHEMA)

    def test_veto_votes_over_http_and_stops_early(self) -> None:
        take = json.dumps({"verdicts": [{"symbol": "BTCUSDT", "verdict": "TAKE", "reason": "with the trend"}]})
        skip = json.dumps({"verdicts": [{"symbol": "BTCUSDT", "verdict": "SKIP", "reason": "stretched"}]})
        o = FakeOllama([skip, "not json", take, take, take])
        try:
            got, info = brain.veto([{"symbol": "BTCUSDT", "side": "LONG", "facts": {"trend_1h": "up"}}], o.url)
        finally:
            o.close()
        self.assertFalse(got["BTCUSDT"]["take"])                                        # one SKIP and one bad answer: 4 TAKEs can't happen
        self.assertEqual(len(o.seen), 2)                                                # so it stopped asking
        self.assertEqual(o.seen[0]["format"], brain.VETO_SCHEMA)
        self.assertEqual((info["asked"], info["valid"]), (2, 1))

    def test_question_too_long_for_the_model_is_a_missed_decision(self) -> None:
        o = FakeOllama(["{}"], prompt_tokens=R.NUM_CTX)
        try:
            got, info = brain.decide([{"symbol": s} for s in R.SYMBOLS], {}, o.url)
        finally:
            o.close()
        self.assertIsNone(got)
        self.assertIn("too long", info["error"])

    def test_ollama_off_is_a_missed_decision_not_a_crash(self) -> None:
        got, info = brain.decide([{"symbol": s} for s in R.SYMBOLS], {}, "http://127.0.0.1:9")
        self.assertIsNone(got)
        self.assertIn("error", info)
        self.assertIsNone(brain.model_digest("http://127.0.0.1:9"))
