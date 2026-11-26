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
- **Crypto** — the Qwen paper bot: account value against a coin flip and against just holding BTC, the latest decision
  with Qwen's reasons, open positions, trades, the log, and the rules.
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
Fake money (US$100,000 start). Live Binance prices for BTC and ETH. Every 5 minutes Qwen says LONG, SHORT or FLAT for each;
code sizes the trade (0.5% of the account at risk), sets a stop and target, charges Binance's 0.05% fee and the spread,
and closes everything for the day after a 3% daily loss. A coin flip runs under the same rules, and "hold BTC" shows what
doing nothing would have made. If Qwen is late or answers badly (for example while you're gaming), that decision counts
as missed. Plutus can answer questions about it, quoting only the live numbers.

## Backups
- `F:\Backups\DDG_Local_Bot_Studio_2026-11-26_before_Claude.zip` — the studio as it was before 26 Nov's work.
- The full code history is in Claude's copy, ready for GitHub once the private repo `DDG_BotStudio` exists.
