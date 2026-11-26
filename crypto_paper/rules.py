"""The written-down rules. Changing any value means a new RULES_VERSION and a fresh record.

v3 (27 Nov 2026), after the first night (v1, 26-27 Nov):
- FLAT closed every trade 5 minutes later, so fees ate the account. Now WAIT keeps a trade open and CLOSE exits on purpose.
- Stops and targets sat on 5-minute ATR, so fees were a large share of every trade. Now they use 1-hour ATR.
- Qwen decides every 15 minutes, from 15-minute, 1-hour and 4-hour data, not the last 5 minutes.
- Added a plain-code "Trend rule" account: if Qwen can't beat a simple rule, use the rule.
- The coin flip and trend rule only open when flat and only exit at their stop, target or the daily stop.
"""

RULES_VERSION = "v3 · 2026-11-27"
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
FILL_AT_BID_ASK = True              # buys fill at the ask, sells at the bid: the live spread is paid
FUNDING_HOURS_UTC = (0, 8, 16)      # perpetual funding times; rate read live, or the trade is flagged
MODEL = "qwen3:8b"
KEEP_ALIVE = "30m"                  # keep Qwen loaded between decisions (a cold start took ~28 s on 26 Nov)
DECISION_TIMEOUT_S = 60
COIN_FLIP_SEED = 20261127
MIN_SAMPLE = 30                     # "Qwen + journal" sees a group's numbers only after this many closed trades (my choice, not a standard)

# Pass bar, written down before any v3 result exists (my choice of numbers, not an industry standard).
# Nothing is judged before each Qwen account has PASS_MIN_TRADES closed trades. Even then it is a first read, not proof.
PASS_MIN_TRADES = 200
PASS_BAR = (f"After at least {PASS_MIN_TRADES} closed trades, a Qwen account counts as useful only if, over the same "
            "period, it beats the coin flip, the trend rule and holding BTC, and its average trade is above zero after "
            "fees, spread and funding. 'Qwen + journal' counts as better than plain Qwen only if it also beats plain Qwen.")
