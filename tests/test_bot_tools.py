"""Bot PC tools (Phase 2.5): a fake Qwen asks to look, then proposes a plan. Uses a temporary studio copy."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

STUDIO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO_ROOT))

import dashboard.server as server  # noqa: E402
from studio import bot_tools, governance, pc_worker  # noqa: E402
from studio.ai_director import OllamaClient  # noqa: E402


class FakeQwen:
    calls: list = []

    def __init__(self, *a, **k):
        self.text_model = "fake-qwen"

    def is_available(self) -> bool:
        return True

    _messages = staticmethod(OllamaClient._messages)

    def chat_raw(self, messages, tools=None, model=None):
        FakeQwen.calls.append(messages)
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return {"content": "", "tool_calls": [{"function": {"name": "pc_look", "arguments": {"path": FakeQwen.dl}}}]}
        if len(tool_msgs) == 1:
            return {"content": "", "tool_calls": [{"function": {"name": "pc_propose_plan", "arguments": json.dumps(
                {"title": "Tidy Downloads", "moves": [{"src": FakeQwen.dl + "/old.zip", "dest": "QUARANTINE"}]})}}]}
        seen = json.loads(tool_msgs[0]["content"])
        return {"content": f"I found {seen['total']} item(s). A plan is waiting for your approval."}


class TestBotTools(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ddg_tools_"))
        self.studio = self.tmp / "studio_copy"
        for d in ("config", "dashboard"):
            shutil.copytree(STUDIO_ROOT / d, self.studio / d, ignore=shutil.ignore_patterns("__pycache__"))
        (self.studio / "logs").mkdir()
        self.home = self.tmp / "home"
        self.dl = self.home / "Downloads"
        self.dl.mkdir(parents=True)
        (self.dl / "old.zip").write_bytes(b"z" * 100)
        self._g = (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home, pc_worker.PLANS_FILE)
        governance.PERMISSIONS_FILE = self.tmp / "d" / "perm.json"
        governance.PROPOSALS_FILE = self.tmp / "d" / "props.json"
        governance.QUARANTINE_ROOT = self.tmp / "q"
        governance._home = lambda: self.home
        pc_worker.PLANS_FILE = self.tmp / "d" / "plans.json"
        governance.save_permissions({"scope": "custom", "custom_paths": [str(self.dl)]})
        FakeQwen.dl = str(self.dl)
        FakeQwen.calls = []
        footage = self.tmp / "footage"
        for sub in ("01_Raw_Inbox", "03_Ready_For_Review", "04_Approved_Exports"):
            (footage / sub).mkdir(parents=True)
        with mock.patch.object(server, "OllamaClient", FakeQwen):
            self.h = server.make_handler(self.studio, footage)

    def tearDown(self) -> None:
        (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home, pc_worker.PLANS_FILE) = self._g
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_wants_tools(self) -> None:
        self.assertTrue(bot_tools.wants_tools("can you tidy my Downloads folder"))
        self.assertTrue(bot_tools.wants_tools(r"what's in C:\Users\User"))
        self.assertFalse(bot_tools.wants_tools("hi how are you"))

    def test_look_then_propose_creates_pending_plan_and_moves_nothing(self) -> None:
        with mock.patch.object(server, "OllamaClient", FakeQwen):
            code, _, out = server.dispatch_http_request(self.h, "POST", "/api/bots/Heimdall/chat",
                                                        json.dumps({"message": "please tidy my downloads folder"}).encode())
        self.assertEqual(code, 200, out)
        reply = json.loads(out)
        self.assertIn("1 item", reply["reply"])
        self.assertTrue(reply["reply_source"].endswith("+tools"))
        plans = pc_worker.list_plans()
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["status"], "pending_markus_approval")
        self.assertEqual(plans[0]["proposer"], "Heimdall")
        self.assertTrue((self.dl / "old.zip").exists(), "a bot must never move anything itself")

    def test_blocked_place_is_reported_not_read(self) -> None:
        out = json.loads(bot_tools.run("pc_look", {"path": str(self.home / ".ssh")}, "Heimdall"))
        self.assertIn("error", out)

    def test_old_history_not_sent(self) -> None:
        chats = {"chats": {"Heimdall": [
            {"sender": "Heimdall", "text": "You have FULL READ/WRITE access", "timestamp_aest": "2026-11-25T11:54:15+10:00"},
            {"sender": "Heimdall", "text": "new honest reply", "timestamp_aest": "2026-11-26T17:00:00+10:00"}]}}
        (self.studio / "logs" / "bot_chats.json").write_text(json.dumps(chats), encoding="utf-8")
        with mock.patch.object(server, "OllamaClient", FakeQwen):
            server.dispatch_http_request(self.h, "POST", "/api/bots/Heimdall/chat", json.dumps({"message": "tidy my files"}).encode())
        sent = json.dumps(FakeQwen.calls[0])
        self.assertNotIn("FULL READ/WRITE", sent)
        self.assertIn("new honest reply", sent)


if __name__ == "__main__":
    unittest.main()
