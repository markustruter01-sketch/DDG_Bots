"""The written-down rules. Changing any value means a new RULES_VERSION and a fresh record.

v5 (27 Nov 2026, 13:00): on v4, both Qwen accounts said WAIT 44 times out of 44 in 2.5 hours (the prompt said "WAIT is a
good answer most of the time"), so they produced no data. Now, for every coin with nothing open and no limit blocking it,
Qwen must pick LONG or SHORT and say how sure it is. The cost limits below cap how often that can trade. Only the Qwen
prompt and this label changed; every number below is the same as v4. (Not tried in the replay first: Markus asked for
it live, and the replay needs his PC.)

v4 (27 Nov 2026), after the code audit of the same day:
- Trades fill at the price AFTER Qwen answers, and stops are checked while it thinks (v3 filled at the price from before).
- New account "Trend + Qwen veto": the trend rule proposes each trade, Qwen may only TAKE or SKIP it, by 4 votes of 5,
  from facts worked out by code. It can only ever trade less than the trend rule, never more.
- New account "Veto, spot fees": the same verdicts on the kind of venue an Australian retail account can open
  (long only, no borrowing, Kraken Pro entry-tier fees).
- Cost limits for every account: a cooldown after any exit, a cap on entries per day, and BTC and ETH in the same
  direction count as one bet.
- 200 coin-flip accounts instead of one, so "beat the coin flip" means beating luck, not one lucky or unlucky draw.
- The model file and the prompts are part of the rules: if either changes, the record starts fresh.
- Limit-order entries, other exits and the event blackout exist for the replay rig (crypto_paper/replay.py) and are OFF
  here until a held-out month supports them.

v3 (27 Nov 2026), after the first night (v1, 26-27 Nov):
- FLAT closed every trade 5 minutes later, so fees ate the account. Now WAIT keeps a trade open and CLOSE exits on purpose.
- Stops and targets sat on 5-minute ATR, so fees were a large share of every trade. Now they use 1-hour ATR.
- Qwen decides every 15 minutes, from 15-minute, 1-hour and 4-hour data, not the last 5 minutes.
- Added a plain-code "Trend rule" account: if Qwen can't beat a simple rule, use the rule.
- The coin flip and trend rule only open when flat and only exit at their stop, target or the daily stop.
"""

RULES_VERSION = "v5 · 2026-11-27"
START_BALANCE = 100_000.0           # fake US dollars
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TICK_SECONDS = 2                    # price check (stops and targets)
DECISION_SECONDS = 900              # decisions every 15 minutes, on the quarter hour
RISK_PER_TRADE = 0.005              # 0.5% of equity lost if the stop is hit
MAX_NOTIONAL_PER_POSITION = 1.5     # position size at most 1.5x equity
MAX_GROSS_LEVERAGE = 3.0            # all positions together at most 3x equity
ATR_INTERVAL = "1h"                 # stops and targets are measured on 1-hour candles
STOP_ATR = 1.5                      # stop distance = 1.5 x ATR(14, 1h)
TARGET_ATR = 2.5                    # profit target = 2.5 x ATR(14, 1h)
DAILY_LOSS_STOP = 0.03              # down 3% since 00:00 Brisbane -> flat, no new trades until tomorrow
TAKER_FEE = 0.0005                  # Binance USD-M futures regular taker fee (support FAQ 360033544231)
MAKER_FEE = 0.0002                  # same FAQ: regular maker fee (only used by limit-order entries)
FILL_AT_BID_ASK = True              # buys fill at the ask, sells at the bid: the live spread is paid
FUNDING_HOURS_UTC = (0, 8, 16)      # perpetual funding times; the settled rate is read from Binance, or the trade is flagged
FUNDING_GRACE_MINUTES = 10          # how long after a funding time the bot keeps trying to read the settled rate
MODEL = "qwen3:8b"
KEEP_ALIVE = "30m"                  # keep Qwen loaded between decisions (a cold start took ~28 s on 26 Nov)
NUM_CTX = 8192                      # the studio's chat must use the same number, or Ollama reloads the model on every switch
DECISION_TIMEOUT_S = 60
COIN_FLIP_SEED = 20261127
MIN_SAMPLE = 30                     # "Qwen + journal" sees a group's numbers only after this many closed trades (my choice, not a standard)

# ── v4: cost limits, the same for every account (my choice of numbers, not a standard) ──
COOLDOWN_MINUTES = 60               # after any exit in a coin, no new trade in that coin for this long
MAX_ENTRIES_PER_DAY = 6             # per account, per Brisbane day
ONE_BET_PER_DIRECTION = True        # BTC and ETH move together: a second trade in the same direction is the same bet twice

# ── v4: the veto account ──
VETO_VOTES = 5                      # Qwen is asked this many times about each proposed trade
VETO_NEED = 4                       # the trade is taken only if at least this many answers say TAKE
VETO_BUDGET_S = 45                  # all the votes together must fit in this; votes not in by then count as SKIP

# ── v4: coin flips ──
FLIP_BANK = 200                     # coin-flip accounts run side by side; a result is ranked against all of them

# ── v4: venues. "futures" is what v1-v3 modelled. "spot" is what an Australian retail account can open. ──
VENUES = {
    "futures": {"taker_fee": TAKER_FEE, "maker_fee": MAKER_FEE, "allow_short": True, "funding": True,
                "max_notional": MAX_NOTIONAL_PER_POSITION, "max_gross": MAX_GROSS_LEVERAGE},
    # Kraken Pro entry tier since 9 Jul 2026: 0.40% maker, 0.80% taker. No shorting, no borrowing, no funding.
    # Prices still come from Binance's book, so this shows the cost of the venue, not Kraken's own prices.
    "spot": {"taker_fee": 0.008, "maker_fee": 0.004, "allow_short": False, "funding": False,
             "max_notional": 1.0, "max_gross": 1.0},
}

# ── v4: options built for the replay rig. OFF live until a held-out month supports them. ──
ENTRY_STYLE = "market"              # "market" (pay the spread and the taker fee) or "limit" (rest at the bid/ask, maker fee, may not fill)
LIMIT_TTL_MINUTES = 15              # an unfilled limit order is dropped after this long
EXIT_STYLE = "fixed"                # "fixed" (stop and target), "breakeven" (stop moves to entry) or "trail" (stop follows, no target)
BREAKEVEN_AFTER_ATR = 1.0           # "breakeven": after the trade is this many ATR in front, the stop moves to the entry price
EVENT_BLACKOUT = False              # no new trades around the scheduled announcements in config/crypto_events.json
BLACKOUT_MINUTES_BEFORE = 30
BLACKOUT_MINUTES_AFTER = 30

# Pass bar, written down before any v4 result exists (my choice of numbers, not an industry standard).
# Nothing is judged before an account has PASS_MIN_TRADES closed trades. Even then it is a first read, not proof.
PASS_MIN_TRADES = 200
PASS_FLIPS_BEATEN = 190             # of the 200 coin flips
PASS_BAR = (f"After at least {PASS_MIN_TRADES} closed trades, a Qwen account counts as useful only if, over the same "
            f"period, it ends above at least {PASS_FLIPS_BEATEN} of the {FLIP_BANK} coin flips, above the trend rule and "
            "above holding BTC, and its average trade is above zero after fees, spread and funding. "
            "'Trend + Qwen veto' must also show that the trades it skipped did worse than the trades it took. "
            "'Qwen + journal' counts as better than plain Qwen only if it also beats plain Qwen.")


def spec(venue: str = "futures", **changes) -> dict:
    """How one account trades: its venue plus the limits and options above. Plain data, so it can be saved and compared."""
    s = {"venue": venue, **VENUES[venue],
         "risk": RISK_PER_TRADE, "stop_atr": STOP_ATR, "target_atr": TARGET_ATR, "daily_stop": DAILY_LOSS_STOP,
         "cooldown_min": COOLDOWN_MINUTES, "max_entries": MAX_ENTRIES_PER_DAY, "one_bet": ONE_BET_PER_DIRECTION,
         "entry": ENTRY_STYLE, "limit_ttl_min": LIMIT_TTL_MINUTES, "exits": EXIT_STYLE,
         "breakeven_after_atr": BREAKEVEN_AFTER_ATR, "blackout": EVENT_BLACKOUT}
    unknown = set(changes) - set(s)
    if unknown:
        raise ValueError(f"Unknown account setting(s): {sorted(unknown)}")
    s.update(changes)
    return s
