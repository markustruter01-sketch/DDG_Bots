"""The written-down rules. Changing any value means a new RULES_VERSION and a fresh record."""

RULES_VERSION = "v1 · 2026-11-26"
START_BALANCE = 100_000.0           # fake US dollars
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TICK_SECONDS = 2                    # price check (stops and targets)
DECISION_SECONDS = 300              # Qwen decides every 5 minutes, on the 5-minute mark
RISK_PER_TRADE = 0.005              # 0.5% of equity lost if the stop is hit
MAX_NOTIONAL_PER_POSITION = 1.5     # position size at most 1.5x equity
MAX_GROSS_LEVERAGE = 3.0            # all positions together at most 3x equity
STOP_ATR = 1.5                      # stop distance = 1.5 x ATR(14) on 5-minute candles
TARGET_ATR = 2.5                    # profit target = 2.5 x ATR(14)
DAILY_LOSS_STOP = 0.03              # down 3% since 00:00 Brisbane -> flat, no new trades until tomorrow
TAKER_FEE = 0.0005                  # Binance USD-M futures regular taker fee (support FAQ 360033544231)
FILL_AT_BID_ASK = True              # buys fill at the ask, sells at the bid: the live spread is paid
FUNDING_HOURS_UTC = (0, 8, 16)      # perpetual funding times; rate read live, or the trade is flagged
MODEL = "qwen3:8b"
KEEP_ALIVE = "30m"                  # keep Qwen loaded between decisions (a cold start took ~28 s on 26 Nov)
DECISION_TIMEOUT_S = 60
COIN_FLIP_SEED = 20261126
