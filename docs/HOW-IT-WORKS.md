# How the DDG Bot Studio works (for Markus)

## Starting and stopping
- It starts by itself when you log in, and a check every 5 minutes restarts it (and the crypto bot) if either stops.
  Restarts are noted in `logs\watchdog.log`.
- **Restart DDG Bot Studio.bat** stops and starts everything, then shows the version.
- **Remove Always-On.bat** turns the automatic start off.
- The switch top-right pauses the bots and routines.

## Pages
- **Core** — the orb and the chat side by side. Pick who to talk to under the orb. *Waiting for you* lists everything
  that needs your OK (tidy-up plans, quarantine requests, social drafts) with buttons. The orb shows *Thinking* only while
  a bot is actually answering.
- **Bots & Chat** — the full team list, rules and skills, group chats.
- **Crypto** — the Qwen paper bot: six fake-money accounts, 200 coin flips and "hold BTC" side by side, the latest
  decisions with Qwen's reasons, open positions, trades, the log, the rules, and whether Qwen's veto is helping.
- **Video Studio** — the video inbox and jobs.
- **Schedules & System** — routines with their last result, the tidy-up tool, quarantine, social queue, images.

## Tidying your PC
- Ask a bot ("what's taking space in my Downloads?") — it looks (read only) and can propose a plan. Or use
  *Tidy Up Your PC* yourself.
- A plan is a dry run until you approve it. Then everything is checked again, moved one by one and recorded.
  **Undo this plan** puts it all back. "Delete" always means moving to `F:\DDG_Quarantine`, which only you empty.
- Never touchable, whatever the setting: Windows, Program Files, AppData, key folders, code history (`.git`),
  `F:\Backups`, the AI models, the browser sign-ins, the quarantine and the studio itself.

## Routines (Brisbane time)
| When | Who | What |
|---|---|---|
| Weekdays 7:00 | Heimdall | List of up to 5 things waiting on you, from real records |
| Monday 9:00 | Heimdall | Weekly review, written by Qwen from the studio's facts only |
| Weekdays 17:00 | Saga | Marketing brief (videos, social queue) |
| Friday 7:00 | Saga | Draft content ideas for next week |
| Mon/Wed/Fri 21:15 | Saga | Drafts one X post into the approval queue (never posts) |
| Weekdays 13:15 | Tyr | Skipped: no Gmail or Shopify connection yet |

If the studio was off at a routine's time, it runs when the studio comes back within 2 hours; otherwise it is marked
*missed*. Results show on *Schedules & System*.

## The crypto paper bot
Fake money (US$100,000 start each). Live Binance prices for BTC and ETH. Rules v4 (27 Nov). Every 15 minutes:
1. **Plain code first.** The trend rule (1-hour EMA20/EMA50) and the coin flips act. They enter only when flat and exit
   only at their stop or target.
2. **Trend + Qwen veto.** For each trade the trend rule has just opened, Qwen is asked five times: TAKE or SKIP? It
   sees facts worked out by code ("uptrend, 1.2 ATR strong", "volatility high for the month"), not raw numbers. The
   trade is copied only on four TAKEs; no answer in 45 seconds means SKIP. So this account can only trade less than
   the trend rule, never more, and every trade it skipped has a known result in the trend rule's account.
3. **Veto, spot fees.** The same verdicts on the kind of venue an Australian retail account can open: long only, no
   borrowing, 0.8% a side. It shows what the idea costs outside Binance futures.
4. **Qwen** picks LONG, SHORT, WAIT or CLOSE for each coin. **Qwen + journal** does the same, plus it sees code-counted
   results of its own closed trades (numbers only after 30).

The same for every account:
- Code sizes the trade (0.5% of the account at risk), sets the stop (1.5x 1-hour ATR) and target (2.5x), charges the
  fee and the spread, and closes everything for the day after a 3% daily loss.
- Cost limits: 60 minutes' cooldown after an exit in a coin, at most 6 new trades a day, and BTC and ETH in the same
  direction count as one bet.
- A model account trades at the price *after* its answer arrived, and stops are checked while it thinks.
- Funding is charged at the rate Binance actually settled. If that can't be read within 10 minutes, the trade is flagged.
- If Qwen is late or answers badly (for example while you're gaming), that decision counts as missed.

Reading the result:
- **200 coin flips** run under the same rules. Each account shows how many of them it is ahead of. One coin flip can
  be lucky; 200 show what luck looks like.
- **Did the veto help?** (under *Rules* on the Crypto page) splits the trend rule's own trades into the ones Qwen took
  and the ones it skipped. The veto is worth something only if the skipped ones did clearly worse.
- Pass bar (written before results): see `PASS_BAR` in `crypto_paper/rules.py`. Nothing is judged before 200 closed trades.
- A changed rule, a changed prompt or a changed model file starts a fresh record by itself; the old one is archived.
- If the bot's own code changes, it stops itself and the watchdog starts the new version within a few minutes.
- Everything Qwen was shown and answered is kept in `data\crypto\decisions.jsonl`.

### Trying an idea on past prices first (the replay)
The live bot gives about 100 decisions a day. The replay runs the same rules over months of past candles in minutes.
In a terminal in the studio folder:
1. `.venv\Scripts\python -m crypto_paper.replay download --days 180` — past 1-minute candles and funding (public data, no keys).
2. `.venv\Scripts\python -m crypto_paper.replay arms` — the list of things that can be compared.
3. `.venv\Scripts\python -m crypto_paper.replay run --arms trend,trend_limit,trend_breakeven,trend_blackout,flips` — plain
   code only, takes minutes. Add `veto` or `qwen` to ask Qwen; that takes hours the first time, then the answers are
   remembered.
4. The last 30 days are held back. Look at them **once**, with `--final`, for the one idea you picked on the earlier
   days. Every look is written to `data\crypto\replay\final_looks.jsonl`.

Limits of the replay: 1-minute candles, not every tick; a fixed spread; a limit order counts as filled only once the
price has traded a little past it. It is good for throwing bad ideas out, not for proving a good one.

Built but OFF on the live bot until a held-out month supports them: limit-order entries, a stop that moves to entry or
follows the price, no new trades around US rate decisions and inflation figures (`config/crypto_events.json`), Qwen's
thinking mode, and other models. Each is a replay arm.

History: on the first night (v1) FLAT closed every trade 5 minutes later and fees ate the account (Qwen -4.83%, coin
flip -6.23%, hold BTC +0.39%, 26-27 Nov). v3 fixed that. v4 followed the code audit of 27 Nov. Plutus can answer
questions about the bot, quoting only the live numbers.

## Backups
- `F:\Backups\DDG_Local_Bot_Studio_2026-11-26_before_Claude.zip` — the studio as it was before 26 Nov's work.
- The full code history is in Claude's copy, ready for GitHub once the private repo `DDG_BotStudio` exists.
