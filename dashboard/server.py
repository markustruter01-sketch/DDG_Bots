"""Local DDG Night Glass v6.1 Bot Management & Video Review Server strictly bound to 127.0.0.1:8765."""

from __future__ import annotations

import hmac
import io
import json
import mimetypes
import secrets
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone, timedelta
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

AEST = timezone(timedelta(hours=10))
STUDIO_VERSION = "2026.11.26-core-chat"
STARTED_AT = datetime.now(AEST).isoformat(timespec="seconds")
TOKEN_PLACEHOLDER = b"__DDG_SESSION_TOKEN__"
# Bots only see chat history from after the honesty fixes, so old false answers ("full access") are not repeated.
HONEST_SINCE = "2026-11-26T13:00:00+10:00"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import social
from studio import tts as tts_engine
from studio import governance
from studio import pc_worker
from studio import bot_tools
from studio import image_gen
from studio.ai_director import OllamaClient
from studio.memory import BotMemory
from studio.calibration import log_feedback
from studio.models import (
    STUDIO_ROOT,
    load_json,
    load_rules,
    load_settings,
    now_aest_iso,
    save_json,
)
from studio.opusclip_bridge import OpusClipPolicyGuard
from studio.pipeline import VIDEO_EXTS, run_job
from studio.scheduler import build_heimdall_daily_list, validate_marketing_mode_schedule
from studio.vram_baton import is_gpu_busy_for_user


DEFAULT_BOT_ROSTER: list[dict[str, Any]] = [
    {
        "name": "Heimdall",
        "title": "GM / COO",
        "active": True,
        "zone": "Executive & Ops",
        "summary": "Owns the 7:00am weekday list (<=5 asks with recommendations), project coordination, and Monday 9:00am review.",
        "tools": ["sql_read", "schedule_digest", "preflight_audit", "code_review", "system_audit"],
    },
    {
        "name": "Marketing",
        "title": "Marketing & Video Director (Saga)",
        "active": True,
        "zone": "net_ddg_mkt (DDG Only)",
        "summary": "Owns DDG YouTube vlogs/Shorts, @DDGCompany X posts, IG Shorts reposts, and Threads of Empire launch.",
        "tools": [
            "ffmpeg_studio",
            "whisperx",
            "night_glass_gfx",
            "opusclip_guard",
            "artcraft_photocraft",
            "artcraft_filmcraft",
            "imagemagick",
            "yt_dlp",
            "moviepy_motion",
            "draft_social",
        ],
    },
    {
        "name": "Tyr",
        "title": "CDC Venture Manager",
        "active": True,
        "zone": "net_cdc (Drafts-Only)",
        "summary": "Owns Cattle Dog Coffee Christmas sale, B2B gifting drafts (Spam Act compliant), Shopify, and CDC inbox.",
        "tools": ["cdc_gmail_drafts_only", "shopify_read", "spam_act_linter"],
    },
    {
        "name": "Mímir",
        "title": "Chief Scientist & Skeptic",
        "active": False,
        "zone": "Paused Bench",
        "summary": "Read-only research & fact-checking. Stopped at A$0 until DDG exits Marketing Mode.",
        "tools": ["research_read_only"],
    },
    {
        "name": "Njord",
        "title": "Venture Manager / Rainmaker",
        "active": False,
        "zone": "Paused Bench",
        "summary": "Outbound B2B drafts. Stopped at A$0 during Marketing Mode.",
        "tools": ["b2b_drafts"],
    },
    {
        "name": "Daedalus",
        "title": "R&D Lab",
        "active": False,
        "zone": "Paused Bench",
        "summary": "Sandboxed technical prototypes. Stopped at A$0 during Marketing Mode.",
        "tools": ["sandbox_proto"],
    },
    {
        "name": "Harald",
        "title": "Chief of Staff",
        "active": False,
        "zone": "Paused Bench",
        "summary": "Cross-project coordination. Stopped at A$0 during Marketing Mode.",
        "tools": ["notes_read"],
    },
    {
        "name": "Hermes",
        "title": "Operations Manager",
        "active": False,
        "zone": "Paused Bench",
        "summary": "SOPs and operational health checks. Stopped at A$0 during Marketing Mode.",
        "tools": ["ops_check"],
    },
    {
        "name": "Plutus",
        "title": "Finance & Analytics",
        "active": False,
        "zone": "Paused Bench (Air-gapped from DDG Finance)",
        "summary": "Read-only CDC/ad P&L analytics. Never touches DDG Finance trading.",
        "tools": ["analytics_read_only"],
    },
]


CAPABILITIES_PROMPT = (
    "WHAT YOU CAN DO: talk with Markus and draft text (posts, emails, plans, scripts, checklists). "
    "When Markus asks for an image, the studio makes it for you. "
    "When Markus asks about his files, the studio gives you read-only tools to look at folders and to propose a "
    "move plan; he approves or rejects it in 'Waiting for you', and every plan can be undone. "
    "WHAT YOU CANNOT DO: move, change or delete files yourself; run programs; browse the web; send email or post anything. "
    "If Markus asks for those, say plainly that you can't, and say what he can do instead. "
    "Do not offer to run scripts or automations; you may write a script as text for Markus to review. "
    "Never say or imply you did something you did not do, and never describe file contents or folders a tool has not shown you. "
    "You never place trades. Never invent numbers, facts, dates or status; if you don't know, say so. "
)


def _norm_bot_key(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name.strip().lower())
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    if ascii_only in ("freya", "saga"):
        return "marketing"
    return ascii_only


def _find_bot_def(name: str) -> dict[str, Any] | None:
    key = _norm_bot_key(name)
    for b in DEFAULT_BOT_ROSTER:
        if _norm_bot_key(b["name"]) == key:
            return b
    return None


def _bot_offline_reply(bot: dict[str, Any], message: str) -> str:
    msg_low = message.lower()
    if bot["name"] == "Heimdall":
        return (
            f"[{bot['name']} · Offline Local Charter]\n"
            "• Status: Local Ollama is currently offline, so this response is deterministic.\n"
            "• Guardrail: Max 5 points in the 7:00am list; DA-04 (Hypest key rotation + 2FA) remains flagged.\n"
            "• Recommendation: Run scripts\\setup_local_env.ps1 so qwen3:8b answers live at A$0."
        )
    if bot["name"] == "Tyr":
        return (
            f"[{bot['name']} · Offline Local Charter]\n"
            "• CDC-only isolation active: Gmail is hard-locked to DRAFTS ONLY (Markus presses Send).\n"
            "• Legal linter enforced: Spam Act consent/unsubscribe + 'charities like the RSPCA' wording.\n"
            f"• Received task: '{message[:120]}' — start Ollama for live local draft generation."
        )
    if "opusclip" in msg_low:
        return (
            f"[{bot['name']} · Offline Local Charter]\n"
            "• OpusClip policy: check credits before submit (261 baseline, warn >140), raw source only, private project.\n"
            "• Never publish raw OpusClip output; use Video Studio -> OpusClip Pro Credit Guard."
        )
    return (
        f"[{bot['name']} · Offline Local Charter]\n"
        f"• Role: {bot['title']} ({bot['zone']}).\n"
        f"• Received: '{message[:120]}'. Start Ollama (scripts\\setup_local_env.ps1) for live A$0 qwen3:8b replies."
    )


def make_handler(studio_root: Path, footage_root: Path):
    settings = load_settings(studio_root)
    rules = load_rules(studio_root)
    subdirs = settings["footage_subdirs"]
    session_token = secrets.token_urlsafe(32)
    dash_port = int(settings.get("dashboard", {}).get("port", 8765))
    allowed_hosts = {f"127.0.0.1:{dash_port}", f"localhost:{dash_port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}
    assets_root = (studio_root / "assets").resolve()
    logs_root = (studio_root / "logs").resolve()
    index_html_path = (studio_root / "dashboard" / "index.html").resolve()
    if not index_html_path.exists():
        index_html_path = (STUDIO_ROOT / "dashboard" / "index.html").resolve()

    inbox_root = (footage_root / subdirs["inbox"]).resolve()
    review_root = (footage_root / subdirs["review"]).resolve()
    approved_root = (footage_root / subdirs["approved"]).resolve()
    pause_flag = (logs_root / "studio_paused.flag").resolve()
    roster_state_path = (logs_root / "bot_roster_state.json").resolve()
    chats_path = (logs_root / "bot_chats.json").resolve()
    groups_path = (logs_root / "group_chats.json").resolve()
    custom_rules_path = (logs_root / "bot_rules.json").resolve()
    memory = BotMemory(logs_root / "bot_memory.sqlite3")
    skills_dir = (studio_root / "skills").resolve()
    skills_dir.mkdir(parents=True, exist_ok=True)
    active_runs: dict[str, dict[str, Any]] = {}
    run_lock = threading.Lock()

    def _load_custom_rules() -> dict[str, Any]:
        cr = {}
        if custom_rules_path.exists():
            cr = dict(load_json(custom_rules_path))
        base = {
            "global_rules": cr.get("global_rules", "Reply in clear, concise plain English. Never invent numbers or facts."),
            "active_skills": cr.get("active_skills", ["Concise Bullet Points", "Australian English"]),
            "bot_rules": cr.get("bot_rules", {}),
        }
        # Scan uploaded skill/rule MD files
        md_skills = []
        if skills_dir.exists():
            for f in sorted(skills_dir.glob("*.md")):
                try:
                    txt = f.read_text(encoding="utf-8").strip()
                    md_skills.append({"name": f.name, "content": txt})
                except Exception:
                    pass
        base["uploaded_skills"] = md_skills
        return base

    def _build_rules_prompt(bot_name: str) -> str:
        cr = _load_custom_rules()
        parts = []
        gr = str(cr.get("global_rules", "")).strip()
        if gr:
            parts.append(f"Global user rules: {gr}")
        skills = [str(s).strip() for s in (cr.get("active_skills") or []) if str(s).strip()]
        if skills:
            parts.append(f"Active skills/style: {', '.join(skills)}.")
        for ms in (cr.get("uploaded_skills") or []):
            parts.append(f"User Skill File [{ms['name']}]: {ms['content']}")
        br = str((cr.get("bot_rules") or {}).get(bot_name, "")).strip()
        if br:
            parts.append(f"Specific rules for {bot_name}: {br}")
        return " ".join(parts)

    def _load_roster_doc() -> dict[str, Any]:
        if roster_state_path.exists():
            return dict(load_json(roster_state_path))
        return {"active": {b["name"]: bool(b["active"]) for b in DEFAULT_BOT_ROSTER}, "names": {}}

    def _load_roster_states() -> dict[str, bool]:
        doc = _load_roster_doc()
        return dict(doc.get("active", {b["name"]: bool(b["active"]) for b in DEFAULT_BOT_ROSTER}))

    def _load_bot_names() -> dict[str, str]:
        doc = _load_roster_doc()
        return dict(doc.get("names", {}))

    def _load_chats() -> dict[str, list[dict[str, Any]]]:
        if chats_path.exists():
            return dict(load_json(chats_path).get("chats", {}))
        return {}

    def _load_groups() -> list[dict[str, Any]]:
        if groups_path.exists():
            return list(load_json(groups_path).get("groups", []))
        return [
            {
                "id": "ddg-hq",
                "name": "DDG Team Room",
                "members": ["Heimdall", "Marketing", "Tyr"],
                "history": [],
            }
        ]

    def _save_groups(groups: list[dict[str, Any]]) -> None:
        save_json(groups_path, {"groups": groups, "updated_at_aest": now_aest_iso()})

    def _post_proactive_bot_message(bot_name: str, message: str, source: str = "proactive_daemon") -> None:
        try:
            chats_now = _load_chats()
            hist_now = chats_now.setdefault(bot_name, [])
            ts_now = now_aest_iso()
            hist_now.append({
                "sender": bot_name,
                "text": message,
                "timestamp_aest": ts_now,
                "source": source
            })
            chats_now[bot_name] = hist_now[-50:]
            save_json(chats_path, {"chats": chats_now})
            try:
                memory.add(f"bot:{bot_name}", bot_name, message, ts_now)
            except Exception:
                pass
        except Exception as e:
            print(f"[Proactive] Error logging message for {bot_name}: {e}")

    def _fire_windows_toast(title: str, message: str) -> None:
        def _run() -> None:
            try:
                clean_title = title.replace("'", "''").replace("\n", " ")
                clean_msg = message.replace("'", "''").replace("\n", " ")[:120]
                ps_script = f"""
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
                $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                $textNodes = $template.GetElementsByTagName('text')
                $textNodes.Item(0).AppendChild($template.CreateTextNode('{clean_title}')) | Out-Null
                $textNodes.Item(1).AppendChild($template.CreateTextNode('{clean_msg}')) | Out-Null
                $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('DDG.LocalBotStudio')
                $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
                $notifier.Show($toast)
                """
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    watcher_state = {
        "active": True,
        "last_checked": "",
        "processed_count": 0,
        "last_processed_file": "",
    }

    def _scan_inbox_now() -> list[str]:
        inbox_candidates = [
            footage_root / "01_Raw_Inbox",
            studio_root / "data" / "footage" / "01_Raw_Inbox"
        ]
        processed = []
        for inbox in inbox_candidates:
            if not inbox.exists():
                continue
            try:
                for file in sorted(inbox.glob("*")):
                    if not file.is_file() or file.suffix.lower() not in VIDEO_EXTS:
                        continue
                    try:
                        if file.stat().st_size == 0:
                            continue
                    except Exception:
                        continue
                    archive_dir = inbox.parent / "05_Archive_Raw"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        from studio import pipeline
                        res = pipeline.run_job(source_video=file, mode="preview", offline=False, studio_root=studio_root, footage_root=footage_root)
                        jid = res.get("job_id", file.stem)
                        dest = archive_dir / file.name
                        try:
                            file.replace(dest)
                        except Exception:
                            pass
                        msg_mkt = (
                            f"🎬 **[Auto-Ingest Complete]** Processed raw footage `{file.name}`.\n"
                            f"• **Job ID:** `{jid}`\n"
                            f"• **Pipeline:** Preview 1080p cut, WhisperX transcript, and Night Glass HUD ready.\n"
                            f"• **Review:** Opened in **03_Ready_For_Review**."
                        )
                        _post_proactive_bot_message("Marketing", msg_mkt, "auto_ingest_watcher")
                        _post_proactive_bot_message("Heimdall", f"Video Studio Ingest: `{file.name}` -> `{jid}` ready in 03_Ready_For_Review.", "auto_ingest_watcher")
                        _fire_windows_toast("DDG Video Studio", f"Ingested {file.name}: Preview and transcript ready!")
                        processed.append(file.name)
                        watcher_state["processed_count"] += 1
                        watcher_state["last_processed_file"] = file.name
                    except Exception as e:
                        print(f"[Auto-Watcher] Failed processing {file.name}: {e}")
            except Exception:
                pass
        return processed

    def _start_background_watcher() -> None:
        def _loop() -> None:
            seen_sizes: dict[Path, int] = {}
            inbox_candidates = [
                footage_root / "01_Raw_Inbox",
                studio_root / "data" / "footage" / "01_Raw_Inbox"
            ]
            while True:
                time.sleep(6)
                if pause_flag.exists():
                    continue
                watcher_state["last_checked"] = now_aest_iso()
                for inbox in inbox_candidates:
                    if not inbox.exists():
                        continue
                    try:
                        for file in sorted(inbox.glob("*")):
                            if not file.is_file() or file.suffix.lower() not in VIDEO_EXTS:
                                continue
                            try:
                                cur_size = file.stat().st_size
                            except Exception:
                                continue
                            if cur_size == 0:
                                continue
                            prev = seen_sizes.get(file)
                            seen_sizes[file] = cur_size
                            if prev is not None and prev == cur_size:
                                busy, _why = is_gpu_busy_for_user(
                                    paused_processes=settings["gpu"]["pause_on_processes"],
                                    vram_threshold_mb=settings["gpu"]["vram_busy_threshold_mb"],
                                )
                                if busy:  # was `if is_gpu_busy_for_user():` - a tuple, always true, so nothing ever ran
                                    continue
                                archive_dir = inbox.parent / "05_Archive_Raw"
                                archive_dir.mkdir(parents=True, exist_ok=True)
                                try:
                                    from studio import pipeline
                                    res = pipeline.run_job(source_video=file, mode="preview", offline=False, studio_root=studio_root, footage_root=footage_root)
                                    jid = res.get("job_id", file.stem)
                                    dest = archive_dir / file.name
                                    try:
                                        file.replace(dest)
                                        seen_sizes.pop(file, None)
                                    except Exception:
                                        pass
                                    msg_mkt = (
                                        f"🎬 **[Auto-Ingest Complete]** New footage `{file.name}` ingested from `01_Raw_Inbox`.\n"
                                        f"• **Job ID:** `{jid}`\n"
                                        f"• **Pipeline:** Preview cut, WhisperX transcript, and Night Glass HUD generated.\n"
                                        f"• **Status:** Ready in **03_Ready_For_Review**."
                                    )
                                    _post_proactive_bot_message("Marketing", msg_mkt, "auto_ingest_watcher")
                                    _post_proactive_bot_message("Heimdall", f"Video Studio Ingest: `{file.name}` -> `{jid}` ready in 03_Ready_For_Review.", "auto_ingest_watcher")
                                    _fire_windows_toast("DDG Video Studio", f"Ingested {file.name}: Preview and transcript ready!")
                                    watcher_state["processed_count"] += 1
                                    watcher_state["last_processed_file"] = file.name
                                except Exception as e:
                                    print(f"[Auto-Watcher] Error processing {file.name}: {e}")
                    except Exception:
                        pass
        threading.Thread(target=_loop, daemon=True).start()

    _start_background_watcher()

    scheduler_state = {
        "active": True,
        "last_7am_date": "",
        "last_monday_date": "",
    }

    def _waiting_on_markus() -> list[dict[str, str]]:
        waiting: list[dict[str, str]] = []
        props = governance.list_proposals("pending_markus_approval")
        if props:
            waiting.append({"item": f"{len(props)} item(s) proposed for quarantine",
                            "recommendation": "Review the checks in Governance, then approve or veto each one."})
        try:
            posts = [q for q in social.list_queue(studio_root) if q.get("status") == "pending_approval"]
        except Exception:
            posts = []
        if posts:
            waiting.append({"item": f"{len(posts)} social post draft(s) waiting",
                            "recommendation": "Approve or reject them in the social queue."})
        ok = OllamaClient(base_url=settings["ollama"]["base_url"], timeout_s=2).is_available()
        if not ok:
            waiting.append({"item": "Local AI (Ollama) is not answering",
                            "recommendation": "Start it from the dashboard or run scripts\\fix_models.bat."})
        return waiting

    def _trigger_7am_brief() -> dict[str, Any]:
        brief = build_heimdall_daily_list(studio_root=studio_root, max_items=5, waiting=_waiting_on_markus())
        items_txt = []
        for i, it in enumerate(brief.get("items", [])):
            items_txt.append(f"{i+1}. **{it.get('item')}**\n   • *Recommendation:* {it.get('recommendation')}")

        now_dt = datetime.now(AEST)
        today_str = now_dt.strftime("%Y-%m-%d")
        full_msg = (
            f"🛡️ **[Heimdall · 7:00am Executive Brief · {today_str} AEST]**\n"
            f"Good morning Markus. Here are your weekday priority actions (max 5 items):\n\n"
            + "\n\n".join(items_txt)
            + "\n\n*Awaiting founder directives. Studio running locally at A$0 compute.*"
        )
        _post_proactive_bot_message("Heimdall", full_msg, "proactive_scheduler")
        _fire_windows_toast("Heimdall · 7:00am Brief", f"Good morning Markus! 5 daily priorities compiled for {today_str}.")
        scheduler_state["last_7am_date"] = today_str
        return brief

    def _start_proactive_scheduler() -> None:
        def _loop() -> None:
            while True:
                time.sleep(20)
                if pause_flag.exists():
                    continue
                now_aest = datetime.now(AEST)
                today_str = now_aest.strftime("%Y-%m-%d")

                # Weekday 7:00am AEST (Mon-Fri, hour == 7)
                if now_aest.weekday() < 5 and now_aest.hour == 7 and scheduler_state["last_7am_date"] != today_str:
                    try:
                        _trigger_7am_brief()
                        print(f"[Scheduler] Dispatched 7:00am daily brief for {today_str}")
                    except Exception as e:
                        print(f"[Scheduler] Error running 7:00am brief: {e}")

                # Monday 9:00am AEST
                if now_aest.weekday() == 0 and now_aest.hour == 9 and scheduler_state["last_monday_date"] != today_str:
                    scheduler_state["last_monday_date"] = today_str
                    try:
                        ai_ok = OllamaClient(base_url=settings["ollama"]["base_url"], timeout_s=2).is_available()
                        ai_line = (f"Local AI ({settings['ollama']['text_model']}) answered a check just now."
                                   if ai_ok else "Local AI is NOT answering right now.")
                        rev_msg = (
                            f"🛡️ **[Heimdall · Monday 9:00am Executive Review · {today_str} AEST]**\n"
                            f"Weekly executive review:\n"
                            f"1. **Marketing & Video (Saga):** Threads of Empire vlogs, @DDGCompany X posts, and Shorts review queue.\n"
                            f"2. **Cattle Dog Coffee (Tyr):** Christmas B2B campaign active (strict Spam Act consent, Gmail locked to Drafts).\n"
                            f"3. **Doomsday Daycare (UE5):** Target 60 FPS mobile/PC performance budgets intact.\n"
                            f"4. **Infrastructure:** {ai_line}"
                        )
                        _post_proactive_bot_message("Heimdall", rev_msg, "proactive_scheduler")
                        _fire_windows_toast("Heimdall · Monday 9:00am Review", "Monday 9:00am Executive Review compiled.")
                        print(f"[Scheduler] Dispatched Monday 9:00am review for {today_str}")
                    except Exception as e:
                        print(f"[Scheduler] Error running Monday review: {e}")
        threading.Thread(target=_loop, daemon=True).start()

    _start_proactive_scheduler()

    class StudioHandler(BaseHTTPRequestHandler):
        token = session_token

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _host_ok(self) -> bool:
            """Refuse DNS-rebinding: the Host header must be this studio's own address."""
            return (self.headers.get("Host") or "").strip().lower() in allowed_hosts

        def _post_ok(self) -> bool:
            """A change request must come from the studio's own dashboard page."""
            origin = (self.headers.get("Origin") or "").strip().lower()
            if origin and origin not in allowed_origins:
                return False
            sent = self.headers.get("X-DDG-Token") or ""
            return hmac.compare_digest(sent.encode("utf-8"), session_token.encode("utf-8"))

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")

        def _send_json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._security_headers()
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._host_ok():
                self._send_json(403, {"error": "Refused: wrong address. Open http://127.0.0.1:%d" % dash_port})
                return

            if path == "/api/health":
                self._send_json(200, {"ok": True, "version": STUDIO_VERSION, "started_at_aest": STARTED_AT})
                return

            if path == "/":
                body = index_html_path.read_bytes().replace(TOKEN_PLACEHOLDER, session_token.encode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._security_headers()
                self.end_headers()
                self.wfile.write(body)
                return

            if path.startswith("/assets/"):
                rel = unquote(path[len("/assets/") :])
                if not rel or ".." in Path(rel).parts:
                    self._send_json(404, {"error": "Asset not found"})
                    return
                target = (assets_root / rel).resolve()
                if not target.is_relative_to(assets_root) or not target.is_file():
                    self._send_json(404, {"error": "Asset not found"})
                    return
                mime, _ = mimetypes.guess_type(str(target))
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/api/bots":
                states = _load_roster_states()
                custom_names = _load_bot_names()
                chats = _load_chats()
                bots = []
                for b in DEFAULT_BOT_ROSTER:
                    bots.append(
                        {
                            **b,
                            "display_name": custom_names.get(b["name"], b["name"]),
                            "active": states.get(b["name"], b["active"]),
                            "history": chats.get(b["name"], [])[-25:],
                        }
                    )
                self._send_json(
                    200,
                    {"paused": pause_flag.exists(), "bots": bots, "groups": _load_groups()},
                )
                return

            if path == "/api/groups":
                self._send_json(200, {"groups": _load_groups()})
                return

            if path == "/api/rules":
                self._send_json(200, _load_custom_rules())
                return

            if path == "/api/social":
                self._send_json(
                    200,
                    {
                        "queue": social.list_queue(studio_root)[-40:],
                        "settings": social.get_settings(studio_root),
                        "platforms": {k: v["label"] for k, v in social.PLATFORMS.items()},
                        "profile_dir": str(social.PROFILE_DIR),
                    },
                )
                return

            if path == "/api/tts/status":
                self._send_json(200, {"neural_ready": tts_engine.is_ready(), "voice": tts_engine.VOICE_NAME})
                return

            if path == "/api/inbox":
                files: list[dict[str, Any]] = []
                if inbox_root.exists():
                    for f in sorted(inbox_root.rglob("*")):
                        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                            rel = str(f.relative_to(inbox_root)).replace("\\", "/")
                            files.append(
                                {
                                    "rel_path": rel,
                                    "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                                }
                            )
                with run_lock:
                    runs = list(active_runs.values())[-10:]
                self._send_json(200, {"files": files, "runs": runs})
                return

            if path == "/api/schedule":
                ok, issues = validate_marketing_mode_schedule(rules)
                q_path = logs_root / "daily_digest_queue.json"
                pending = load_json(q_path).get("pending_failures", []) if q_path.exists() else []
                sched = rules.get("marketing_mode_schedules_aest", {})
                self._send_json(
                    200,
                    {
                        "valid": ok,
                        "issues": issues,
                        "timezone": sched.get("timezone", "Australia/Brisbane"),
                        "jobs": sched.get("jobs", []),
                        "pending_failures": pending,
                    },
                )
                return

            if path == "/api/system":
                busy, gpu_status = is_gpu_busy_for_user(
                    paused_processes=settings["gpu"]["pause_on_processes"],
                    vram_threshold_mb=settings["gpu"]["vram_busy_threshold_mb"],
                )
                ollama = OllamaClient(
                    base_url=settings["ollama"]["base_url"],
                    text_model=settings["ollama"]["text_model"],
                    vision_model=settings["ollama"]["vision_model"],
                    timeout_s=2,
                )
                expected_assets = [
                    "DDG_Logo_New.png",
                    "Threads_of_Empire_Cover_1_Percent_v01.png",
                    "DDG Intro 15s (Share).mp4",
                    "DDG Reel Outro 3s (1080x1920).mp4",
                    "DDG Site Loader 5s (1920x1080).webm",
                    "freya_avatar_white.png",
                ]
                assets_status = [
                    {"file": name, "present": (assets_root / name).is_file()} for name in expected_assets
                ]
                self._send_json(
                    200,
                    {
                        "gpu_busy": busy,
                        "gpu_status": gpu_status,
                        "ollama_online": ollama.is_available(),
                        "text_model": settings["ollama"]["text_model"],
                        "footage_root": str(footage_root),
                        "footage_root_exists": footage_root.exists(),
                        "assets": assets_status,
                    },
                )
                return

            if path == "/api/jobs":
                jobs: list[dict[str, Any]] = []
                if review_root.exists():
                    for d in sorted(review_root.iterdir()):
                        mf = d / "job_manifest.json"
                        if d.is_dir() and mf.exists():
                            jobs.append(load_json(mf))
                self._send_json(200, {"paused": pause_flag.exists(), "jobs": jobs})
                return

            if path.startswith("/api/jobs/"):
                jid = unquote(path.split("/api/jobs/", 1)[1]).strip("/")
                job_dir = (review_root / jid).resolve()
                if job_dir.parent != review_root or not (job_dir / "job_manifest.json").exists():
                    self._send_json(404, {"error": "Job not found"})
                    return
                manifest = load_json(job_dir / "job_manifest.json")
                pf_path = job_dir / "preflight_report.json"
                preflight = load_json(pf_path) if pf_path.exists() else {}
                self._send_json(200, {"manifest": manifest, "preflight": preflight})
                return

            if path == "/api/governance/permissions":
                self._send_json(200, governance.load_permissions())
                return

            if path == "/api/governance/proposals":
                self._send_json(200, {"proposals": governance.list_proposals()})
                return

            if path == "/api/images":
                self._send_json(200, {"images": image_gen.list_gallery(), "status": image_gen.get_image_engine_status()})
                return

            if path == "/api/diffusion/status":
                self._send_json(200, image_gen.get_image_engine_status())
                return

            if path == "/api/inbox/watcher_status":
                self._send_json(200, watcher_state)
                return

            if path == "/api/scheduler/status":
                self._send_json(200, scheduler_state)
                return

            if path.startswith("/media/"):
                parts = [unquote(p) for p in path[len("/media/") :].split("/") if p]
                if len(parts) < 1:
                    self._send_json(400, {"error": "Invalid media path"})
                    return
                # Check candidate locations in order
                candidates = [
                    (footage_root / "04_Review_Outbox" / Path(*parts)).resolve(),
                    (review_root / Path(*parts)).resolve(),
                    (footage_root / Path(*parts)).resolve(),
                    (studio_root / "data" / Path(*parts)).resolve(),
                    (studio_root / "assets" / Path(*parts)).resolve(),
                ]
                target = None
                for c in candidates:
                    if c.is_file():
                        target = c
                        break
                if target is None:
                    self._send_json(404, {"error": "Media file not found"})
                    return
                mime, _ = mimetypes.guess_type(str(target))
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            self._send_json(404, {"error": "Not found"})

        def _chat_with_tools(self, ollama: Any, bot: dict[str, Any], sys_prompt: str, msg: str,
                             prior_hist: list[dict[str, str]], stream_mode: bool, record: Any) -> None:
            """Chat where the bot may look at folders and propose a plan (Phase 2.5). Nothing moves without Markus."""
            def emit(ev: dict[str, Any]) -> None:
                if stream_mode:
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                    self.wfile.flush()
            try:
                if stream_mode:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                msgs = ollama._messages(sys_prompt + "\n" + bot_tools.TOOLS_PROMPT, msg, prior_hist)
                reply = ""
                try:
                    for rnd in range(bot_tools.MAX_ROUNDS + 1):
                        m = ollama.chat_raw(msgs, tools=bot_tools.TOOLS if rnd < bot_tools.MAX_ROUNDS else None)
                        calls = m.get("tool_calls") or []
                        if not calls:
                            reply = str(m.get("content") or "").strip()
                            break
                        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
                        for c in calls:
                            fn = c.get("function", {}) or {}
                            name, args = str(fn.get("name", "")), fn.get("arguments") or {}
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except ValueError:
                                    args = {}
                            emit({"thought": bot_tools.describe(name, args) + "\n", "source": "tools"})
                            msgs.append({"role": "tool", "content": bot_tools.run(name, args, bot["name"]), "tool_name": name})
                except Exception as exc:
                    reply = reply or f"I couldn't finish looking ({type(exc).__name__}). Please ask again."
                reply = reply or "I looked, but couldn't put an answer together. Please ask again."
                source = f"ollama:{ollama.text_model}+tools"
                record(reply, source)
                if stream_mode:
                    emit({"token": reply, "source": source})
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    self._send_json(200, {"bot": bot["name"], "reply": reply, "reply_source": source})
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

        def _pc_worker(self, path: str, body: dict[str, Any]) -> None:
            """PC worker (Phase 2). All POST, so every call carries the session token."""
            def num(key: str) -> float | None:
                v = body.get(key)
                return float(v) if v not in (None, "") else None
            try:
                if path == "/api/pc/list":
                    out = pc_worker.list_dir(str(body.get("path", "")))
                elif path == "/api/pc/sizes":
                    out = pc_worker.folder_sizes(str(body.get("path", "")))
                elif path == "/api/pc/search":
                    out = pc_worker.search(str(body.get("path", "")), str(body.get("name") or "*"),
                                           num("older_than_days"), num("min_size_mb"))
                elif path == "/api/pc/duplicates":
                    out = pc_worker.find_duplicates(str(body.get("path", "")), num("min_size_mb") or 1.0)
                elif path == "/api/pc/plans/list":
                    out = {"plans": pc_worker.list_plans()}
                elif path == "/api/pc/plans":
                    proposer = str(body.get("proposer", "Markus"))
                    if proposer.lower() != "markus" and not _find_bot_def(proposer):
                        raise pc_worker.WorkerError(f"Unknown proposer '{proposer}'")
                    moves = body.get("moves")
                    if not isinstance(moves, list):
                        raise pc_worker.WorkerError("'moves' must be a list of {src, dest}.")
                    out = {"plan": pc_worker.create_plan(proposer, str(body.get("title", "")), moves, str(body.get("reason", "")))}
                elif path.startswith("/api/pc/plans/"):
                    rest = path[len("/api/pc/plans/"):].strip("/").split("/")
                    if len(rest) != 2 or rest[1] not in ("approve", "reject", "undo"):
                        raise pc_worker.WorkerError("Use /api/pc/plans/<id>/approve, /reject or /undo.")
                    fn = {"approve": pc_worker.approve_plan, "reject": pc_worker.reject_plan, "undo": pc_worker.undo_plan}[rest[1]]
                    out = {"plan": fn(unquote(rest[0]))}
                else:
                    self._send_json(404, {"error": "Unknown PC worker action."})
                    return
                self._send_json(200, out)
            except (pc_worker.WorkerError, FileNotFoundError, NotADirectoryError, PermissionError) as exc:
                self._send_json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._host_ok() or not self._post_ok():
                self._send_json(403, {"error": "Refused: changes are only accepted from the studio dashboard on this PC."})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                body = {}

            if path == "/api/governance/permissions":
                doc = governance.load_permissions()
                doc["scope"] = str(body.get("scope", doc["scope"])).strip()
                if isinstance(body.get("custom_paths"), list):
                    doc["custom_paths"] = [str(p) for p in body["custom_paths"]]
                try:
                    self._send_json(200, governance.save_permissions(doc))
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path == "/api/governance/propose":
                bot_name = str(body.get("bot_name", "Heimdall")).strip()
                target_path = str(body.get("target_path", "")).strip()
                reason = str(body.get("reason", "")).strip()
                if not target_path:
                    self._send_json(400, {"error": "Target path is required"})
                    return
                bdef = _find_bot_def(bot_name)
                proposer = "Markus" if bot_name.lower() == "markus" else (bdef["name"] if bdef else None)
                if proposer is None:
                    self._send_json(400, {"error": f"Unknown proposer '{bot_name}'"})
                    return
                try:
                    prop = governance.create_deletion_proposal(proposer, target_path, reason)
                    self._send_json(201, {"proposal": prop})
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path.startswith("/api/pc/"):
                self._pc_worker(path, body)
                return

            if path.startswith("/api/governance/restore/"):
                prop_id = unquote(path[len("/api/governance/restore/") :]).strip("/")
                try:
                    self._send_json(200, {"proposal": governance.restore_proposal(prop_id)})
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path.startswith("/api/governance/resolve/"):
                prop_id = unquote(path[len("/api/governance/resolve/") :]).strip("/")
                decision = str(body.get("decision", "approve")).strip()
                note = str(body.get("note", "")).strip()
                try:
                    res = governance.markus_resolve_proposal(prop_id, decision, note)
                    self._send_json(200, {"proposal": res})
                except Exception as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path == "/api/images/generate":
                prompt = str(body.get("prompt", "")).strip()
                bot_name = str(body.get("bot_name", "Marketing")).strip()
                style = str(body.get("style", "Night Glass Futuristic")).strip()
                if not prompt:
                    self._send_json(400, {"error": "Prompt cannot be empty"})
                    return
                try:
                    entry = image_gen.generate_image(prompt, bot_name=bot_name, style=style)
                    self._send_json(201, {"image": entry})
                except Exception as exc:
                    self._send_json(500, {"error": f"Image generation failed: {exc}"})
                return

            if path == "/api/pause":
                pause_flag.parent.mkdir(parents=True, exist_ok=True)
                if pause_flag.exists():
                    pause_flag.unlink()
                    self._send_json(200, {"paused": False, "message": "Studio resumed"})
                else:
                    pause_flag.write_text(now_aest_iso(), encoding="utf-8")
                    self._send_json(200, {"paused": True, "message": "Studio paused"})
                return

            if path.startswith("/api/bots/") and path.endswith("/toggle"):
                raw_name = unquote(path[len("/api/bots/") : -len("/toggle")]).strip("/")
                bot = _find_bot_def(raw_name)
                if bot is None:
                    self._send_json(404, {"error": f"Unknown bot '{raw_name}'"})
                    return
                doc = _load_roster_doc()
                states = dict(doc.get("active", _load_roster_states()))
                new_val = not states.get(bot["name"], bot["active"])
                states[bot["name"]] = new_val
                doc["active"] = states
                doc["updated_at_aest"] = now_aest_iso()
                save_json(roster_state_path, doc)
                self._send_json(200, {"bot": bot["name"], "active": new_val})
                return

            if path.startswith("/api/bots/") and path.endswith("/rename"):
                raw_name = unquote(path[len("/api/bots/") : -len("/rename")]).strip("/")
                bot = _find_bot_def(raw_name)
                if bot is None:
                    self._send_json(404, {"error": f"Unknown bot '{raw_name}'"})
                    return
                new_display = str(body.get("display_name", "")).strip()
                if not new_display or len(new_display) > 40:
                    self._send_json(400, {"error": "Display name must be 1-40 characters"})
                    return
                doc = _load_roster_doc()
                names = dict(doc.get("names", {}))
                names[bot["name"]] = new_display
                doc["names"] = names
                doc["updated_at_aest"] = now_aest_iso()
                save_json(roster_state_path, doc)
                self._send_json(200, {"bot": bot["name"], "display_name": new_display})
                return

            if path == "/api/tts":
                try:
                    wav = tts_engine.synthesize_wav(str(body.get("text", "")))
                except Exception as exc:
                    self._send_json(503, {"error": f"Neural voice unavailable: {exc}"})
                    return
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(len(wav)))
                    self.end_headers()
                    self.wfile.write(wav)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    pass
                return

            if path == "/api/social/draft":
                try:
                    item = social.add_draft(str(body.get("platform", "x")), str(body.get("text", "")), str(body.get("by", "Marketing")), studio_root)
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(201, {"item": item})
                return

            if path == "/api/social/login":
                try:
                    self._send_json(200, social.open_login(str(body.get("platform", "x")), studio_root))
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path == "/api/social/settings":
                self._send_json(200, social.set_settings(body, studio_root))
                return

            if path.startswith("/api/social/") and (path.endswith("/approve") or path.endswith("/reject")):
                action = "approve" if path.endswith("/approve") else "reject"
                iid = unquote(path[len("/api/social/") : -len("/" + action)]).strip("/")
                if action == "reject":
                    it = social.set_status(iid, "rejected", studio_root=studio_root)
                    self._send_json(200 if it else 404, {"item": it} if it else {"error": "Not found"})
                    return
                social.set_status(iid, "approved", studio_root=studio_root)
                try:
                    self._send_json(200, social.publish(iid, studio_root))
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                return

            if path == "/api/rules":
                cr = _load_custom_rules()
                if "global_rules" in body:
                    cr["global_rules"] = str(body.get("global_rules", "")).strip()
                if "active_skills" in body and isinstance(body["active_skills"], list):
                    cr["active_skills"] = [str(s).strip() for s in body["active_skills"] if str(s).strip()]
                if "bot_name" in body and "bot_rule" in body:
                    bdef = _find_bot_def(str(body["bot_name"]))
                    if bdef:
                        br = dict(cr.get("bot_rules") or {})
                        br[bdef["name"]] = str(body.get("bot_rule", "")).strip()
                        cr["bot_rules"] = br
                if "upload_file_name" in body and "upload_file_content" in body:
                    raw_fn = Path(str(body["upload_file_name"])).name
                    if raw_fn.lower().endswith(".md") and all(c.isalnum() or c in " _-." for c in raw_fn) and len(raw_fn) <= 80:
                        target_file = skills_dir / raw_fn
                        target_file.write_text(str(body["upload_file_content"]), encoding="utf-8")
                if "delete_skill" in body:
                    del_fn = Path(str(body["delete_skill"])).name
                    del_target = skills_dir / del_fn
                    if del_target.exists():
                        del_target.unlink()
                cr["updated_at_aest"] = now_aest_iso()
                save_doc = {
                    "global_rules": cr["global_rules"],
                    "active_skills": cr["active_skills"],
                    "bot_rules": cr["bot_rules"],
                    "updated_at_aest": cr["updated_at_aest"]
                }
                save_json(custom_rules_path, save_doc)
                self._send_json(200, _load_custom_rules())
                return

            if path == "/api/groups":
                gname = str(body.get("name", "")).strip()
                members = [m for m in (body.get("members") or []) if _find_bot_def(str(m)) is not None]
                if not gname:
                    self._send_json(400, {"error": "Group name is required"})
                    return
                if len(members) < 2:
                    self._send_json(400, {"error": "Select at least 2 bots for a group chat"})
                    return
                canonical_members = [_find_bot_def(str(m))["name"] for m in members]
                groups = _load_groups()
                gid = "grp-" + "".join(c for c in gname.lower() if c.isalnum())[:16] + f"-{len(groups) + 1}"
                new_group = {"id": gid, "name": gname, "members": canonical_members, "history": []}
                groups.append(new_group)
                _save_groups(groups)
                self._send_json(201, {"group": new_group})
                return

            if path.startswith("/api/groups/") and path.endswith("/chat"):
                gid = unquote(path[len("/api/groups/") : -len("/chat")]).strip("/")
                msg = str(body.get("message", "")).strip()
                if not msg:
                    self._send_json(400, {"error": "Empty message"})
                    return
                groups = _load_groups()
                grp = next((g for g in groups if g["id"] == gid), None)
                if grp is None:
                    self._send_json(404, {"error": f"Unknown group '{gid}'"})
                    return

                custom_names = _load_bot_names()
                offline_only = bool(body.get("offline", False))
                ts = now_aest_iso()
                hist = grp.setdefault("history", [])
                hist.append({"sender": "Markus", "text": msg, "timestamp_aest": ts})

                # If user @mentioned specific bots in the group, only those reply; otherwise all members reply
                msg_low = msg.lower()
                mentioned = []
                for mname in grp["members"]:
                    dname = custom_names.get(mname, mname)
                    if f"@{mname.lower()}" in msg_low or f"@{dname.lower()}" in msg_low:
                        mentioned.append(mname)
                responders = mentioned if mentioned else list(grp["members"])

                ollama = None
                if not offline_only:
                    cand = OllamaClient(
                        base_url=settings["ollama"]["base_url"],
                        text_model=settings["ollama"]["text_model"],
                        vision_model=settings["ollama"]["vision_model"],
                        timeout_s=45,
                    )
                    if cand.is_available():
                        ollama = cand

                stream_group = bool(body.get("stream", False)) and ollama is not None
                prior_group = list(hist[:-1])[-14:]  # everything before the message we just appended
                replies = []
                sse_open = False

                def _sse(obj: dict[str, Any]) -> None:
                    self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
                    self.wfile.flush()

                try:
                    if stream_group:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()
                        sse_open = True

                    for mname in responders:
                        bdef = _find_bot_def(mname)
                        if not bdef:
                            continue
                        dname = custom_names.get(mname, mname)
                        reply_text = ""
                        reply_source = "offline_charter"
                        if sse_open:
                            _sse({"bot": dname, "bot_id": mname, "start": True})
                        if ollama is not None:
                            extra_rules = _build_rules_prompt(mname)
                            recall_txt = memory.format_recall(f"group:{gid}", msg)
                            sys_prompt = (
                                f"You are {dname} ({bdef['title']}) in a DDG team group chat with Markus and {', '.join(grp['members'])}. "
                                f"Zone: {bdef['zone']}. Duty: {bdef['summary']}\n"
                                "You are an employee of Digital Dynamics Group (DDG), running on Markus's own PC with a local AI model. "
                                f"{CAPABILITIES_PROMPT}"
                                "Keep your reply concise (2-4 sentences) and stay in your lane. Do not speak for other bots. "
                                f"{extra_rules}"
                                + (f"\n\n{recall_txt}" if recall_txt else "")
                            )
                            hist_msgs = []
                            for h in prior_group + replies:
                                if h.get("source") == "offline_charter" or h.get("timestamp_aest", "") < HONEST_SINCE:
                                    continue
                                if h.get("sender") == "Markus":
                                    hist_msgs.append({"role": "user", "content": h["text"]})
                                elif h.get("bot_id") == mname:
                                    hist_msgs.append({"role": "assistant", "content": h["text"]})
                                else:
                                    hist_msgs.append({"role": "user", "content": f"[{h.get('sender')}]: {h['text']}"})
                            try:
                                if sse_open:
                                    chunks = []
                                    for piece in ollama.chat_text_stream(sys_prompt, msg, history=hist_msgs):
                                        if isinstance(piece, dict):
                                            if "thought" in piece:
                                                _sse({"bot": dname, "bot_id": mname, "thought": piece["thought"]})
                                            elif "token" in piece:
                                                chunks.append(piece["token"])
                                                _sse({"bot": dname, "bot_id": mname, "token": piece["token"]})
                                        else:
                                            chunks.append(str(piece))
                                            _sse({"bot": dname, "bot_id": mname, "token": str(piece)})
                                    reply_text = "".join(chunks).strip()
                                else:
                                    reply_text = ollama.chat_text(sys_prompt, msg, history=hist_msgs)
                                reply_source = f"ollama:{ollama.text_model}"
                            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                                return
                            except Exception:
                                reply_text = ""
                        if not reply_text:
                            reply_text = _bot_offline_reply(bdef, msg)
                            if sse_open:
                                _sse({"bot": dname, "bot_id": mname, "token": reply_text})
                        entry = {"sender": dname, "bot_id": mname, "text": reply_text, "timestamp_aest": now_aest_iso(), "source": reply_source}
                        replies.append(entry)
                        if sse_open:
                            _sse({"bot": dname, "bot_id": mname, "end": True, "source": reply_source})
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return

                hist.extend(replies)
                grp["history"] = hist[-60:]
                _save_groups(groups)
                memory.add(f"group:{gid}", "Markus", msg, ts)
                for r in replies:
                    if r["source"] != "offline_charter":
                        memory.add(f"group:{gid}", r["sender"], r["text"], r["timestamp_aest"])
                if sse_open:
                    try:
                        _sse({"done": True})
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    except Exception:
                        pass
                    return
                self._send_json(200, {"group_id": gid, "replies": replies})
                return

            if path.startswith("/api/bots/") and path.endswith("/chat"):
                raw_name = unquote(path[len("/api/bots/") : -len("/chat")]).strip("/")
                bot = _find_bot_def(raw_name)
                if bot is None:
                    self._send_json(404, {"error": f"Unknown bot '{raw_name}'"})
                    return
                msg = str(body.get("message", "")).strip()
                if not msg:
                    self._send_json(400, {"error": "Empty message"})
                    return

                offline_only = bool(body.get("offline", False))
                stream_mode = bool(body.get("stream", False))
                reply_text = ""
                reply_source = "offline_charter"

                ollama = None
                if not offline_only:
                    cand = OllamaClient(
                        base_url=settings["ollama"]["base_url"],
                        text_model=settings["ollama"]["text_model"],
                        vision_model=settings["ollama"]["vision_model"],
                        timeout_s=45,
                    )
                    if cand.is_available():
                        ollama = cand

                extra_rules = _build_rules_prompt(bot["name"])
                recall_txt = memory.format_recall(f"bot:{bot['name']}", msg)

                def _record_bot_turn(reply: str, source: str) -> None:
                    chats_now = _load_chats()
                    hist_now = chats_now.setdefault(bot["name"], [])
                    ts_now = now_aest_iso()
                    hist_now.append({"sender": "Markus", "text": msg, "timestamp_aest": ts_now})
                    hist_now.append({"sender": bot["name"], "text": reply, "timestamp_aest": ts_now, "source": source})
                    chats_now[bot["name"]] = hist_now[-50:]
                    save_json(chats_path, {"chats": chats_now})
                    if source != "offline_charter":
                        memory.add(f"bot:{bot['name']}", "Markus", msg, ts_now)
                        memory.add(f"bot:{bot['name']}", bot["name"], reply, ts_now)

                # Automatic Intent Interceptor: If Markus asks the bot to generate/create an image, execute it directly!
                msg_low = msg.lower()
                image_keywords = [
                    "generate an image", "create an image", "generate a background", "create a background",
                    "make an image", "draw an image", "render an image", "generate a picture", "create a picture",
                    "create a beautiful background", "image generating", "generate artwork", "create artwork",
                    "generate graphic", "create graphic", "make a background", "make artwork"
                ]
                is_image_intent = any(k in msg_low for k in image_keywords)
                if is_image_intent:
                    clean_prompt = msg
                    for prefix in [
                        "create a beautiful background of what you think space will look like with a nice satellite flying through it",
                        "create a beautiful background of ", "generate an image of ", "create an image of ",
                        "make an image of ", "generate a background of ", "create a background of ",
                        "render an image of ", "generate a picture of ", "create a picture of ",
                        "draw an image of "
                    ]:
                        if prefix in clean_prompt.lower():
                            parts = clean_prompt.lower().split(prefix, 1)
                            clean_prompt = parts[1] if len(parts) > 1 and parts[1].strip() else prefix
                            break

                    if stream_mode:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()

                        def _send_img_progress(thought_msg: str, pct: int = 0) -> None:
                            try:
                                ev = {"thought": thought_msg, "progress": pct, "source": "creative_engine"}
                                self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                                self.wfile.flush()
                            except Exception:
                                pass

                        try:
                            _send_img_progress(f"🎨 Initializing creative neural canvas for prompt: '{clean_prompt[:60]}...' (100% Free / Local A$0)...", 10)
                            entry = image_gen.generate_image(clean_prompt.strip(), bot_name=bot["name"], progress_callback=_send_img_progress)
                            img_reply = (
                                f"🎨 **Generated Image Successfully!**\n\n"
                                f"**Prompt:** {clean_prompt.strip()}\n"
                                f"**File Saved:** `{entry['path']}`\n\n"
                                f"![Generated Graphic]({entry['url']})\n\n"
                                f"*(Rendered via {entry['engine']} · A$0.00 compute. Full-res view available in **Schedules & System -> Marketing Image Studio**)*"
                            )
                            _record_bot_turn(img_reply, f"local_creative_engine:{entry['engine']}")
                            self.wfile.write(f"data: {json.dumps({'token': img_reply, 'source': entry['engine']})}\n\ndata: [DONE]\n\n".encode("utf-8"))
                            self.wfile.flush()
                        except Exception as img_exc:
                            err_msg = f"⚠️ Image generation error: {img_exc}"
                            self.wfile.write(f"data: {json.dumps({'token': err_msg, 'source': 'error'})}\n\ndata: [DONE]\n\n".encode("utf-8"))
                            self.wfile.flush()
                        return
                    else:
                        try:
                            entry = image_gen.generate_image(clean_prompt.strip(), bot_name=bot["name"])
                            img_reply = (
                                f"🎨 **Generated Image Successfully!**\n\n"
                                f"**Prompt:** {clean_prompt.strip()}\n"
                                f"**File Saved:** `{entry['path']}`\n\n"
                                f"![Generated Graphic]({entry['url']})\n\n"
                                f"*(Rendered via {entry['engine']} · A$0.00 compute. Full-res view available in **Schedules & System -> Marketing Image Studio**)*"
                            )
                            _record_bot_turn(img_reply, f"local_creative_engine:{entry['engine']}")
                            self._send_json(200, {"bot": bot["name"], "reply": img_reply, "reply_source": entry["engine"]})
                        except Exception as img_exc:
                            self._send_json(500, {"error": f"Image generation error: {img_exc}"})
                        return

                prior_hist = [
                    {"role": "user" if h.get("sender") == "Markus" else "assistant", "content": h.get("text", "")}
                    for h in _load_chats().get(bot["name"], [])[-4:]
                    if h.get("source") != "offline_charter" and h.get("timestamp_aest", "") >= HONEST_SINCE
                ]
                sys_prompt = (
                    f"You are {bot['name']}, {bot['title']} at Digital Dynamics Group (DDG). "
                    f"Zone: {bot['zone']}. Duty: {bot['summary']}\n"
                    "You run on Markus's own PC with a local AI model.\n"
                    f"{CAPABILITIES_PROMPT}\n"
                    f"Keep replies concise, professional, and helpful in plain Australian English. {extra_rules}"
                )

                if ollama is not None and bot_tools.wants_tools(msg):
                    self._chat_with_tools(ollama, bot, sys_prompt, msg, prior_hist, stream_mode, _record_bot_turn)
                    return

                if stream_mode and ollama is not None:
                    headers_sent = False
                    try:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.end_headers()
                        headers_sent = True
                        full_chunks = []
                        for piece in ollama.chat_text_stream(sys_prompt, msg, history=prior_hist):
                            if isinstance(piece, dict):
                                if "thought" in piece:
                                    event_data = json.dumps({"thought": piece["thought"], "source": f"ollama:{ollama.text_model}"})
                                    self.wfile.write(f"data: {event_data}\n\n".encode("utf-8"))
                                    self.wfile.flush()
                                elif "token" in piece:
                                    full_chunks.append(piece["token"])
                                    event_data = json.dumps({"token": piece["token"], "source": f"ollama:{ollama.text_model}"})
                                    self.wfile.write(f"data: {event_data}\n\n".encode("utf-8"))
                                    self.wfile.flush()
                            else:
                                full_chunks.append(str(piece))
                                event_data = json.dumps({"token": str(piece), "source": f"ollama:{ollama.text_model}"})
                                self.wfile.write(f"data: {event_data}\n\n".encode("utf-8"))
                                self.wfile.flush()
                        reply_text = "".join(full_chunks).strip()
                        reply_source = f"ollama:{ollama.text_model}"
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        _record_bot_turn(reply_text, reply_source)
                        return
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                        return
                    except Exception as exc:
                        if headers_sent:
                            try:
                                err = json.dumps({"token": f"\n[Local AI error: {type(exc).__name__}]", "source": "error"})
                                self.wfile.write(f"data: {err}\n\ndata: [DONE]\n\n".encode("utf-8"))
                                self.wfile.flush()
                            except Exception:
                                pass
                            return

                if ollama is not None and not reply_text:
                    try:
                        reply_text = ollama.chat_text(sys_prompt, msg, history=prior_hist)
                        reply_source = f"ollama:{ollama.text_model}"
                    except Exception:
                        reply_text = ""

                if not reply_text:
                    reply_text = _bot_offline_reply(bot, msg)

                _record_bot_turn(reply_text, reply_source)
                self._send_json(200, {"bot": bot["name"], "reply": reply_text, "reply_source": reply_source})
                return

            if path.startswith("/api/bots/") and path.endswith("/clear"):
                raw_name = unquote(path[len("/api/bots/") : -len("/clear")]).strip("/")
                bot = _find_bot_def(raw_name)
                if bot is None:
                    self._send_json(404, {"error": f"Unknown bot '{raw_name}'"})
                    return
                chats_now = _load_chats()
                chats_now[bot["name"]] = []
                save_json(chats_path, {"chats": chats_now})
                self._send_json(200, {"cleared": True, "bot": bot["name"]})
                return

            if path == "/api/inbox/process":
                rel = str(body.get("file", "")).strip()
                mode = str(body.get("mode", "preview")).strip()
                if mode not in ("preview", "full", "shorts", "audit"):
                    self._send_json(400, {"error": f"Invalid mode '{mode}'"})
                    return
                if not rel or ".." in Path(rel).parts:
                    self._send_json(400, {"error": "Invalid inbox file path"})
                    return
                target = (inbox_root / rel).resolve()
                if not target.is_relative_to(inbox_root) or not target.is_file():
                    self._send_json(404, {"error": "Inbox video file not found"})
                    return

                run_id = f"run_{target.stem}_{int(len(active_runs) + 1)}"
                with run_lock:
                    active_runs[run_id] = {
                        "run_id": run_id,
                        "file": rel,
                        "mode": mode,
                        "status": "running",
                        "started_at_aest": now_aest_iso(),
                    }

                def _worker() -> None:
                    try:
                        run_job(
                            target,
                            mode=mode,
                            offline=bool(body.get("offline", False)),
                            studio_root=studio_root,
                            footage_root=footage_root,
                        )
                        with run_lock:
                            active_runs[run_id]["status"] = "done"
                    except Exception as exc:
                        with run_lock:
                            active_runs[run_id]["status"] = "error"
                            active_runs[run_id]["error"] = str(exc)

                threading.Thread(target=_worker, daemon=True).start()
                self._send_json(202, {"run_id": run_id, "status": "running", "file": rel, "mode": mode})
                return

            if path == "/api/opusclip/check":
                mins = float(body.get("source_minutes", 0.0))
                guard = OpusClipPolicyGuard(
                    credits_remaining=int(rules["opusclip"]["remaining_credits_baseline"]),
                    warn_over_credits=int(rules["opusclip"]["warn_over_credits"]),
                    credits_per_source_min=int(rules["opusclip"]["credits_per_source_min"]),
                )
                self._send_json(200, guard.check_credit_budget(mins))
                return

            if path == "/api/heimdall/brief":
                brief = _trigger_7am_brief()
                self._send_json(200, brief)
                return

            if path == "/api/heimdall/brief/trigger":
                brief = _trigger_7am_brief()
                self._send_json(200, {"success": True, "brief": brief})
                return

            if path == "/api/inbox/scan_now":
                results = _scan_inbox_now()
                self._send_json(200, {"scanned": True, "processed": results})
                return

            if path == "/api/ollama/start":
                # Check if already running
                cand = OllamaClient(
                    base_url=settings["ollama"]["base_url"],
                    text_model=settings["ollama"]["text_model"],
                    vision_model=settings["ollama"]["vision_model"],
                    timeout_s=3,
                )
                if cand.is_available():
                    self._send_json(200, {"running": True, "message": "Ollama is already running and reachable."})
                    return
                try:
                    # Spawn ollama serve in background
                    subprocess.Popen(["ollama", "serve"], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    # Brief wait to see if it starts up
                    time.sleep(2)
                    alive = cand.is_available()
                    self._send_json(200, {"running": alive, "message": "Ollama serve initiated." if alive else "Ollama process launched, initializing..."})
                except Exception as exc:
                    self._send_json(500, {"error": f"Failed to start Ollama: {exc}"})
                return

            if path.startswith("/api/jobs/") and path.endswith("/approve"):
                jid = unquote(path[len("/api/jobs/") : -len("/approve")]).strip("/")
                job_dir = (review_root / jid).resolve()
                mf_path = job_dir / "job_manifest.json"
                pf_path = job_dir / "preflight_report.json"
                if job_dir.parent != review_root or not mf_path.exists() or not pf_path.exists():
                    self._send_json(404, {"error": "Job or preflight report not found"})
                    return
                pf = load_json(pf_path)
                if not pf.get("passed", False):
                    failed_gates = [g["gate_id"] for g in pf.get("gates", []) if not g.get("passed")]
                    self._send_json(
                        409,
                        {
                            "error": f"Approval BLOCKED: preflight failed gates {failed_gates}",
                            "failed_gates": failed_gates,
                        },
                    )
                    return

                dest = approved_root / jid
                dest.mkdir(parents=True, exist_ok=True)
                for f in job_dir.iterdir():
                    if f.is_file():
                        shutil.copy2(f, dest / f.name)
                manifest = load_json(mf_path)
                manifest["status"] = "approved"
                manifest["approved_at_aest"] = now_aest_iso()
                save_json(mf_path, manifest)
                save_json(dest / "job_manifest.json", manifest)
                self._send_json(200, {"status": "approved", "message": f"Approved and exported to {dest}"})
                return

            if path.startswith("/api/jobs/") and path.endswith("/tweak"):
                jid = unquote(path[len("/api/jobs/") : -len("/tweak")]).strip("/")
                job_dir = (review_root / jid).resolve()
                mf_path = job_dir / "job_manifest.json"
                if job_dir.parent != review_root or not mf_path.exists():
                    self._send_json(404, {"error": "Job not found"})
                    return
                note = str(body.get("note", "")).strip()
                if note:
                    log_feedback(note, reason=f"Markus review tweak on {jid}", studio_root=studio_root)
                manifest = load_json(mf_path)
                sc = manifest.setdefault("social_copy", {})
                if "youtube_title" in body:
                    sc["youtube_title"] = body["youtube_title"]
                if "x_post" in body:
                    sc["x_post"] = body["x_post"]
                save_json(mf_path, manifest)
                self._send_json(200, {"message": "Tweak note & social copy saved."})
                return

            self._send_json(404, {"error": "Not found"})

    return StudioHandler


def dispatch_http_request(
    handler_cls: type[BaseHTTPRequestHandler],
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Exercise StudioHandler directly in-process without opening external sockets.

    By default it sends the dashboard's Host and session token; pass ``headers``
    to replace them (the security tests send none or wrong ones)."""
    handler = handler_cls.__new__(handler_cls)
    handler.command = method.upper()
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{handler.command} {path} HTTP/1.1"
    handler.close_connection = True
    handler.client_address = ("127.0.0.1", 0)
    hdrs = Message()
    sent = headers if headers is not None else {"Host": "127.0.0.1:8765", "X-DDG-Token": getattr(handler_cls, "token", "")}
    for k, v in sent.items():
        hdrs[k] = v
    if body:
        hdrs["Content-Length"] = str(len(body))
        hdrs["Content-Type"] = "application/json"
    handler.headers = hdrs
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()

    if handler.command == "GET":
        handler.do_GET()
    elif handler.command == "POST":
        handler.do_POST()
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    raw_resp = handler.wfile.getvalue()
    head, _, resp_body = raw_resp.partition(b"\r\n\r\n")
    head_lines = head.decode("latin-1").split("\r\n")
    status_code = int(head_lines[0].split(" ", 2)[1])
    resp_headers: dict[str, str] = {}
    for line in head_lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()
    return status_code, resp_headers, resp_body


class StudioHTTPServer(ThreadingHTTPServer):
    """On Windows, SO_REUSEADDR lets several servers bind the same port (stale copies hijack requests).
    Disable it so a second launch fails fast instead of silently creating a zombie."""

    allow_reuse_address = False
    daemon_threads = True


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    studio_root: str | Path = STUDIO_ROOT,
    footage_root: str | Path | None = None,
) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost"):
        raise PermissionError("Dashboard MUST bind strictly to localhost/127.0.0.1.")
    settings = load_settings(studio_root)
    f_root = Path(footage_root or settings["footage_root"])
    handler = make_handler(Path(studio_root), f_root)
    return StudioHTTPServer((host, port), handler)


def _warmup_model_async(settings: dict[str, Any]) -> None:
    def _run() -> None:
        try:
            c = OllamaClient(
                base_url=settings["ollama"]["base_url"],
                text_model=settings["ollama"]["text_model"],
                vision_model=settings["ollama"]["vision_model"],
            )
            for _ in range(20):  # Ollama may still be starting up
                if c.is_available():
                    c.warmup()
                    return
                time.sleep(3)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def main() -> None:
    settings = load_settings(STUDIO_ROOT)
    host = settings["dashboard"]["host"]
    port = int(settings["dashboard"]["port"])
    try:
        srv = create_server(host=host, port=port, studio_root=STUDIO_ROOT)
    except OSError as exc:
        print(f"[DDG] Port {port} is already in use ({exc}).")
        print("[DDG] The studio is probably already running - just open http://127.0.0.1:%d" % port)
        time.sleep(8)
        return
    print(f"[DDG Night Glass Dashboard] Listening strictly on http://{host}:{port}")
    _warmup_model_async(settings)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
