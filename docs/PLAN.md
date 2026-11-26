# DDG Bot Studio — plan to make it the best it can be

Written 26 Nov 2026 by Claude (Opus 5.5), after the full audit (`docs/AUDIT-2026-11-26.md`).
The owner is Markus. Claude writes the code; Markus approves anything that touches money, deletes or accounts.

## What it is for

1. **DDG's employees (~90% of use).** Named bots with real jobs: they brief Markus, draft marketing and CDC work, run scheduled routines, and tell the truth about what they did.
2. **PC worker (sometimes).** Tidy and reorganise folders on Markus's PC under strict control: nothing is ever lost, and every change can be undone.
3. **Home of the Qwen crypto paper bot.** Live on the PC, fake money, fun to watch, scored honestly.

## Rules every part of the plan follows

- **Honest:** a bot never claims an ability, result or status it hasn't got or checked.
- **Nothing is lost:** there is no real delete; "delete" means quarantine, and any batch of changes can be undone.
- **Plain code decides, the AI suggests:** the AI proposes; checks, limits and file actions run as plain, tested code.
- **Locked to Markus:** only the dashboard on this PC can make changes, never a website or another program.
- **Small and clean:** each rule, list and setting lives in one place.
- **Every phase ends with a check you can see:** a test, a log line or a screen.

---

## Phase 0 — Safety net (26 Nov) ✅ done except the GitHub repo

| Step | Done when |
|---|---|
| 0.1 Full backup of the studio as found | `F:\Backups\DDG_Local_Bot_Studio_2026-11-26_before_Claude.zip` exists ✅ |
| 0.2 Code history | Baseline commit made; pushed to a private GitHub repo `DDG_BotStudio` once Markus creates it (Claude can't create repos) |
| 0.3 AI models installed | `ollama list` shows `qwen3:8b` and `qwen3-vl:4b`; speed test logged (`scripts\fix_models.bat`) |

## Phase 1 — Lock the doors ✅ live 26 Nov (`2026.11.26-phase1`)

Also 26 Nov: Core home page (orb + chat, Night Glass), bots no longer see pre-fix chat history, Heimdall's false "Full Access" label removed.

| Step | What | Done when |
|---|---|---|
| 1.1 | **Request lock:** a secret made at each launch; every change request must carry it; wrong Host or Origin refused | Tests: a request without the secret → 403; with a wrong Host → 403; from the dashboard → works |
| 1.2 | **Safe chat display:** messages built without running any code; images only from the studio's own `/media/` | A test message with a crafted link shows as plain text |
| 1.3 | **Honest bots:** remove the "full access / never say you can't" prompt text; each bot is told exactly what it can do today | Bot prompts list only real abilities; Monday review checks Ollama before saying it's on |
| 1.4 | **Always-blocked list:** Windows, Program Files, AppData, key and credential folders, `.git`, backups, AI models, browser profiles, the studio's own permission files. No scope can open these, including "full system" | Tests for each blocked place |
| 1.5 | **Quarantine instead of delete:** an approved "delete" moves the item to `F:\DDG_Quarantine\<date>\`, with a Restore button | Test: approve → item in quarantine; restore → back in place |
| 1.6 | **Real checks instead of fake votes:** size, file count, last changed, inside a code repo?, blocked? | Proposals show checks, not invented votes |
| 1.7 | **Fix the broken "propose" request** (it called a function that doesn't exist) | Test passes |
| 1.8 | **Reliable restart:** one `Restart DDG Bot Studio.bat` that stops the old copy by its port, then starts the new one | After a restart, `/api/health` shows the new version |

## Phase 2 — PC worker done properly ✅ all live 26 Nov (2.5 bots look and propose plans from chat: `tools-routines`)

- **2.1 Tools, run by plain code:** list folder, folder sizes, search by name/type/date, find duplicates (by content), read a text file (size-capped), create folder, move/rename, copy. No delete tool.
- **2.2 Change plans:** a bot (or Markus) writes a plan such as "move 214 old installers from Downloads to F:\Archive\Installers". The studio dry-runs it and shows every file, the total size, and warnings (open files, files used in the last 7 days, anything inside a code repo).
- **2.3 One-click approve, then a journal:** each move is recorded; "Undo batch" puts everything back.
- **2.4 Limits per batch:** a maximum file count and size per batch; anything over goes back for a second look. No batch ever touches a blocked place.
- **2.5 Bots use the tools through the same plans:** Qwen proposes plans with Ollama tool-calling; plain code checks and runs them. A bot can never run a change itself.
- **2.6 Quarantine page:** what's there, when, why; Restore; "empty items older than 30 days" only on Markus's click.

## Phase 3 — Always on ✅ 3.1, 3.2, 3.4, 3.5, 3.6 live 26 Nov (`phase3`); 3.3 heartbeat waits on a DDG Control endpoint

Also fixed 26 Nov: the server's video watcher never ran a job (a tuple was used as true/false). Known limit: the GPU guard counts Qwen's own memory, so videos wait while Qwen is loaded; fix with the crypto bot (Phase 5).

### Phase 3 original list

- **3.1 Start at logon** (Task Scheduler) plus a watchdog that restarts the studio if it stops.
- **3.2 One video watcher, not two** (today the launcher starts a second one alongside the server's own).
- **3.3 Heartbeat to DDG Control** every 5 minutes, so "the PC studio is down" shows on Control and your phone.
- **3.4 Windows Update active hours** set to suit you, and a note in the brief after any restart.
- **3.5 GPU guard knows games** (WoW, Diablo IV, Star Citizen, Steam games): heavy AI work waits; the crypto bot gets priority.
- **3.6 One launcher;** the leftover duplicates removed.

## Phase 4 — Real employees: ✅ 4.1 routine runner live 26 Nov (all six routines; Tyr's honestly skipped: no Gmail/Shopify). 4.2 partly (briefs use studio facts; DDG Control/GitHub/Finance data need connections). 4.3–4.6 open

### Phase 4 original list

- **4.1 One job runner** that runs every routine in `rules.json` (today only 2 of 6 run, as canned text).
- **4.2 Briefs from real data, each item showing its source:**
  - DDG Control: bot reports, alerts and approvals waiting.
  - GitHub: open PRs and failing checks across your repos.
  - DDG Finance: status and stops.
  - The crypto bot: yesterday's result.
- **4.3 One team:** local bots read and post to the DDG Control message board, so the Grok bots and the local bots share one picture. *(Markus to decide: is DDG Control the single roster?)*
- **4.4 Real tools per bot,** in place of today's labels:
  - Tyr: Gmail drafts only, with the Spam Act checker.
  - Saga: the video pipeline plus social drafts.
  - Heimdall: briefs and approvals.
  - Plutus: crypto bot reports.
- **4.5 Memory that helps:** per-bot notes Markus can see and edit; no hidden memory.
- **4.6 Phone alerts through DDG Control** for anything waiting on you.

## Phase 5 — Qwen crypto paper bot ✅ built and live 26 Nov (`2026.11.26-crypto`, rules v1)

### Phase 5 original list

- **5.1** Separate folder `DDG_Crypto_Paper` with its own page in Night Glass style. It shares Ollama, with GPU priority.
- **5.2** Live Binance prices; every price tick recorded locally.
- **5.3** Qwen decides every 5 minutes for BTC and ETH: LONG, SHORT or FLAT, a play type and a reason.
- **5.4** Hard limits in plain code:
  - A stop and a profit target on every trade.
  - 0.5% risk per trade, at most 2–3 trades open.
  - A daily loss stop and a leverage cap.
  - Fees and spread charged on every fill.
- **5.5** Two dumb comparison bots with the same limits: buy-and-hold BTC and a coin flip.
- **5.6** Missed decisions are counted (PC off, game running, bad answer).
- **5.7** Plutus reports trades and daily profit and loss; there's a line in the 7am brief and a heartbeat to DDG Control.
- **5.8** Rules written down before the official start; a change restarts the record.

## Phase 6 — Quality ✅ 6.1 tests (39), 6.2 workflow file ready (runs once the GitHub repo exists), 6.3 AGENTS.md, 6.4 HOW-IT-WORKS.md

### Phase 6 original list

- **6.1** Tests for every safety rule (request lock, blocked list, quarantine, undo, limits).
- **6.2** GitHub Actions running the tests on Windows for every change.
- **6.3** `AGENTS.md` so any AI working on the studio follows these rules.
- **6.4** A short `docs/HOW-IT-WORKS.md` for Markus.

## Decisions needed from Markus

1. Create an empty private GitHub repo named `DDG_BotStudio` (Claude can't create repos from here).
2. Phase 4.3: should DDG Control's roster be the single list of employees, with the local bots as the same people running on Qwen?
