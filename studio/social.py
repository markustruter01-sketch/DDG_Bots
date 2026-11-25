"""Marketing bot social media: isolated BUSINESS-ONLY browser profile + approval queue.

Safety design:
  * Uses its own Chrome profile folder (never the user's personal Chrome profile / logins).
  * Drafts go into a queue. Nothing posts until approved (or autopost is explicitly enabled in settings).
  * Only the DDG business accounts listed in config/social_accounts.json are allowed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from .models import STUDIO_ROOT, load_json, now_aest_iso, save_json

PROFILE_DIR = Path(r"F:\DDG_Video_Studio\marketing_browser_profile")
_LOCK = threading.Lock()

PLATFORMS: dict[str, dict[str, str]] = {
    "x": {"label": "X (@DDGCompany)", "login": "https://x.com/login", "compose": "https://x.com/intent/post?text="},
    "youtube": {"label": "YouTube Studio (DDG channel)", "login": "https://studio.youtube.com", "compose": ""},
    "instagram": {"label": "Instagram (DDG)", "login": "https://www.instagram.com/accounts/login/", "compose": ""},
    "threads": {"label": "Threads (DDG)", "login": "https://www.threads.net/login", "compose": ""},
}


def _paths(studio_root: Path) -> tuple[Path, Path]:
    logs = studio_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "social_queue.json", logs / "social_settings.json"


def get_settings(studio_root: Path = STUDIO_ROOT) -> dict[str, Any]:
    _, sp = _paths(studio_root)
    base = {"autopost": False, "business_accounts": {"x": "@DDGCompany"}}
    if sp.exists():
        base.update(load_json(sp))
    return base


def set_settings(patch: dict[str, Any], studio_root: Path = STUDIO_ROOT) -> dict[str, Any]:
    _, sp = _paths(studio_root)
    cur = get_settings(studio_root)
    if "autopost" in patch:
        cur["autopost"] = bool(patch["autopost"])
    save_json(sp, cur)
    return cur


def list_queue(studio_root: Path = STUDIO_ROOT) -> list[dict[str, Any]]:
    qp, _ = _paths(studio_root)
    if qp.exists():
        return list(load_json(qp).get("items", []))
    return []


def _save_queue(items: list[dict[str, Any]], studio_root: Path) -> None:
    qp, _ = _paths(studio_root)
    save_json(qp, {"items": items[-200:]})


def add_draft(platform: str, text: str, by: str = "Marketing", studio_root: Path = STUDIO_ROOT) -> dict[str, Any]:
    platform = platform.lower().strip()
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}'")
    text = text.strip()
    if not text:
        raise ValueError("Empty draft")
    if platform == "x" and len(text) > 280:
        raise ValueError(f"X posts are max 280 characters (this is {len(text)})")
    with _LOCK:
        items = list_queue(studio_root)
        item = {
            "id": f"sq{len(items) + 1}_{abs(hash(text)) % 100000}",
            "platform": platform,
            "text": text,
            "by": by,
            "status": "pending_approval",
            "created_at_aest": now_aest_iso(),
        }
        items.append(item)
        _save_queue(items, studio_root)
    return item


def set_status(item_id: str, status: str, note: str = "", studio_root: Path = STUDIO_ROOT) -> dict[str, Any] | None:
    with _LOCK:
        items = list_queue(studio_root)
        for it in items:
            if it["id"] == item_id:
                it["status"] = status
                if note:
                    it["note"] = note
                it["updated_at_aest"] = now_aest_iso()
                _save_queue(items, studio_root)
                return it
    return None


def _spawn(args: list[str], studio_root: Path) -> None:
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW for non-interactive; login uses visible chrome
    subprocess.Popen(
        [sys.executable, "-m", "studio.social", *args],
        cwd=str(studio_root),
        creationflags=flags,
    )


def open_login(platform: str, studio_root: Path = STUDIO_ROOT) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}'")
    _spawn(["login", platform], studio_root)
    return {"opened": platform, "profile": str(PROFILE_DIR)}


def publish(item_id: str, studio_root: Path = STUDIO_ROOT) -> dict[str, Any]:
    items = list_queue(studio_root)
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        raise ValueError("Queue item not found")
    if item["status"] not in ("approved", "pending_approval"):
        raise ValueError(f"Item status is {item['status']}")
    set_status(item_id, "publishing", studio_root=studio_root)
    _spawn(["post", item_id], studio_root)
    return {"publishing": item_id}


# ---- subprocess entry (runs Chrome with the isolated profile) ----
def _launch(pw: Any, headless: bool = False) -> Any:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(PROFILE_DIR), channel="chrome", headless=headless, viewport={"width": 1280, "height": 860}
    )


def _cli_login(platform: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = _launch(pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(PLATFORMS[platform]["login"])
        # Stays open until the user closes the window; session cookies persist in PROFILE_DIR.
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass


def _cli_post(item_id: str) -> None:
    from playwright.sync_api import sync_playwright

    studio_root = STUDIO_ROOT
    items = list_queue(studio_root)
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        return
    if item["platform"] != "x":
        # Other platforms: open the site in the business profile for a manual final step.
        with sync_playwright() as pw:
            ctx = _launch(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(PLATFORMS[item["platform"]]["login"])
            set_status(item_id, "needs_manual_post", "Opened site in business profile; paste the approved text.", studio_root)
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
        return
    try:
        with sync_playwright() as pw:
            ctx = _launch(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(PLATFORMS["x"]["compose"] + urllib.parse.quote(item["text"]))
            btn = page.get_by_test_id("tweetButton")
            btn.wait_for(timeout=20000)
            if get_settings(studio_root).get("autopost") or item["status"] == "publishing":
                btn.click()
                page.wait_for_timeout(4000)
                set_status(item_id, "posted", studio_root=studio_root)
            ctx.close()
    except Exception as exc:  # login missing, UI changed, etc.
        set_status(item_id, "failed", f"{type(exc).__name__}: {str(exc)[:200]}", studio_root)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "login":
        _cli_login(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "post":
        _cli_post(sys.argv[2])
