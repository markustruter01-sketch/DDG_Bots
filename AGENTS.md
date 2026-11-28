# DDG Bot Studio — rules for any AI working on this code

Owner: Markus (DDG). Claude writes the code. Read `docs/PLAN.md` and `docs/HOW-IT-WORKS.md` first.

## Never break these
1. **Honest bots.** A bot never claims an ability, a result or a status it hasn't got or checked. Prompts list only real
   abilities (`CAPABILITIES_PROMPT` in `dashboard/server.py`; the whole bot prompt is built in `_bot_system_prompt`).
   Routines write only from `_studio_facts()`. Chat goes through `studio/chat_engine.py` only.
2. **Nothing is lost.** There is no delete. "Delete" = move to `F:\DDG_Quarantine` (`studio/governance.py`), and every
   PC plan has an undo journal (`studio/pc_worker.py`). Never add `rmtree`, `unlink` or `os.remove` on user files.
3. **Plain code decides, the AI suggests.** Bots may look (read-only) and *propose* plans (`studio/bot_tools.py`).
   Only Markus approves, in the dashboard. Bots never move files, post, send or trade.
4. **Always-blocked list** (`governance.blocked_reason`) applies in every scope, `full_system` included. Never weaken it.
5. **Locked to this PC.** Every POST needs the session token (`X-DDG-Token`) and the right Host/Origin. Keep it.
6. **Crypto bot = fake money.** No exchange account, no keys, no orders. Rules live in `crypto_paper/rules.py`;
   changing any value means a new `RULES_VERSION` (that starts a fresh record). The prompts in `crypto_paper/brain.py`
   and the model file count as rules too: the bot fingerprints them and starts a fresh record by itself when either
   changes. Try a new idea in the replay (`crypto_paper/replay.py`) first; switch it on live only after its one look
   at the held-out month. Never tune on the held-out month.
7. **Night Glass** (DDG_Control `docs/brand/night-glass.md`): white does the work, colour only as a signal, amber only for
   problems, never red, charts never animate, render user/bot text escaped (`esc`, `jsArg`, `textContent`).

8. **One guardian.** `studio/guardian.py` is the only thing that starts, checks and restarts the studio, the crypto bot
   and the AI engine (Ollama, always with Qwen's folder on F:). The watchdog, the launcher, "Restart DDG Bot
   Studio.bat" and the dashboard's Restart AI all call it. Tests never touch the real engine: plug in a fake model
   (`make_handler(..., chat_stream=...)`, `guardian.System`) and keep `DDG_NO_HEAL` set in CI.

## How to change things
- Python 3.12 (`.venv`), stdlib only for new code. Run `python -m unittest tests.test_security tests.test_pc_worker
  tests.test_bot_tools tests.test_routines tests.test_crypto_paper tests.test_crypto_v4 tests.test_crypto_replay
  tests.test_guardian tests.test_chat_engine` — all must pass. Add tests for every safety rule you touch.
- Bump `STUDIO_VERSION` in `dashboard/server.py` and the line in `Restart DDG Bot Studio.bat`.
- Never commit `logs/`, `data/` or anything with keys.
