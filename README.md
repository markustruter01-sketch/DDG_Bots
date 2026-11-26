# DDG Bots — Local Bot Studio

The bot team for Digital Dynamics Group (DDG), running on one Windows PC with a free local AI model (Qwen through Ollama).
No cloud AI bills, no data leaving the PC.

**What it does**
- **DDG employees:** a team of bots that chat, write daily briefs and run scheduled routines from real studio facts only.
- **Tidy up your PC (carefully):** bots can look at folders and *propose* clean-up plans. Nothing moves until Markus
  approves in the dashboard, every move can be undone, and "delete" means move to quarantine, never real deletion.
  System, secret and backup folders are always blocked.
- **Crypto paper trading (fake money only):** Qwen trades BTC and ETH with fake US$100,000 against a coin flip,
  a plain trend rule and simply holding BTC. No exchange account, no keys, no real orders.
- **Video studio:** checks and edits DDG videos against the house rules (G0–G11), blurring private details.
- **Dashboard:** `http://127.0.0.1:8765`, only reachable from the PC itself and locked with a per-launch session token.

**Start here**
- `docs/HOW-IT-WORKS.md` — plain-English guide.
- `docs/PLAN.md` and `docs/AUDIT-2026-11-26.md` — the plan and the audit behind it.
- `AGENTS.md` — rules any AI working on this code must follow.

**Run it (Windows, Python 3.12)**
1. `powershell -ExecutionPolicy Bypass -File scripts\setup_local_env.ps1` (one time: Ollama, models, Python packages).
2. Double-click `Restart DDG Bot Studio.bat`, then open `http://127.0.0.1:8765`.
3. Optional: `Install Always-On.bat` starts it at login and checks on it every 5 minutes.

**Private files (not in this repo)**
`data/`, `logs/`, `.env` and `config/private_terms.json` (personal words the video blur must hide; see
`config/private_terms.example.json`) stay on the PC.

**Tests**
`python -m unittest tests.test_security tests.test_pc_worker tests.test_bot_tools tests.test_routines tests.test_crypto_paper`
