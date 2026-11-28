"""Bot PC tools (Phase 2.5): a fake Qwen asks to look, then proposes a plan. Uses a temporary studio copy."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO_ROOT))

import dashboard.server as server  # noqa: E402
from studio import bot_tools, governance, pc_worker  # noqa: E402


class FakeQwen:
    """A fake model behind the chat engine's stream function: look, then propose, then answer."""
    calls: list = []
    dl = ""

    @staticmethod
    def stream(base_url, model, messages, tools=None, think=False):
        FakeQwen.calls.append([dict(m) for m in messages])
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            yield "tool_calls", [{"function": {"name": "pc_look", "arguments": {"path": FakeQwen.dl}}}]
        elif len(tool_msgs) == 1:
            yield "tool_calls", [{"function": {"name": "pc_propose_plan", "arguments": json.dumps(
                {"title": "Tidy Downloads", "moves": [{"src": FakeQwen.dl + "/old.zip", "dest": "QUARANTINE"}]})}}]
        else:
            seen = json.loads(tool_msgs[0]["content"])
            yield "token", f"I found {seen['total']} item(s). "
            yield "token", "A plan is waiting for your approval."


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
        self.h = server.make_handler(self.studio, footage, chat_stream=FakeQwen.stream)

    def tearDown(self) -> None:
        (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home, pc_worker.PLANS_FILE) = self._g
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chat_tools_are_read_only_or_propose(self) -> None:
        names = [t["function"]["name"] for t in bot_tools.CHAT_TOOLS]
        self.assertEqual(names, ["pc_look", "pc_sizes", "pc_search", "pc_duplicates", "pc_propose_plan",
                                 "studio_status", "crypto_status"])          # nothing that moves, sends or trades

    def test_look_then_propose_creates_pending_plan_and_moves_nothing(self) -> None:
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
        server.dispatch_http_request(self.h, "POST", "/api/bots/Heimdall/chat", json.dumps({"message": "tidy my files"}).encode())
        sent = json.dumps(FakeQwen.calls[0])
        self.assertNotIn("FULL READ/WRITE", sent)
        self.assertIn("new honest reply", sent)


class TestChatServer(unittest.TestCase):
    """28 Nov overhaul: streamed replies, the date in the prompt, an honest message when the engine is down."""
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ddg_chat_"))
        self.studio = self.tmp / "studio_copy"
        for d in ("config", "dashboard"):
            shutil.copytree(STUDIO_ROOT / d, self.studio / d, ignore=shutil.ignore_patterns("__pycache__"))
        (self.studio / "logs").mkdir()
        footage = self.tmp / "footage"
        for sub in ("01_Raw_Inbox", "03_Ready_For_Review", "04_Approved_Exports"):
            (footage / sub).mkdir(parents=True)
        self.seen = []
        self.mode = "talk"

        def stream(base_url, model, messages, tools=None, think=False):
            self.seen.append({"messages": messages, "tools": tools, "think": think})
            if self.mode == "down":
                from studio.chat_engine import EngineDown
                raise EngineDown("the AI engine said HTTP 404 (model not found)")
            yield "token", "Sure"
            yield "token", " thing."
        self.h = server.make_handler(self.studio, footage, chat_stream=stream)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def chat(self, body):
        return server.dispatch_http_request(self.h, "POST", "/api/bots/Heimdall/chat", json.dumps(body).encode())

    def test_streamed_reply_and_prompt(self) -> None:
        code, _, out = self.chat({"message": "hello", "stream": True})
        self.assertEqual(code, 200)
        text = out.decode() if isinstance(out, bytes) else out
        self.assertIn('"token": "Sure"', text)
        self.assertTrue(text.rstrip().endswith("data: [DONE]"))
        system = self.seen[0]["messages"][0]["content"]
        from datetime import datetime
        self.assertIn(str(datetime.now(server.AEST).year), system)                 # bots know the date now
        self.assertIn("What the studio does not let you do", system)
        self.assertEqual([t["function"]["name"] for t in self.seen[0]["tools"]][-2:], ["studio_status", "crypto_status"])
        self.assertFalse(self.seen[0]["think"])

    def test_think_harder_switch(self) -> None:
        self.chat({"message": "plan my week", "think": True})
        self.assertTrue(self.seen[0]["think"])

    def test_engine_down_gives_an_honest_message_and_no_heal_in_tests(self) -> None:
        self.mode = "down"
        code, _, out = self.chat({"message": "hello"})
        reply = json.loads(out)
        self.assertEqual(code, 200)
        self.assertEqual(reply["reply_source"], "engine_down")
        self.assertIn("isn't answering", reply["reply"])
        self.assertIn("already restarting", reply["reply"])                       # heal is off for a plugged-in model
        chats = json.loads((self.studio / "logs" / "bot_chats.json").read_text())["chats"]["Heimdall"]
        self.mode = "talk"
        self.chat({"message": "again"})                                             # the failed turn isn't fed back
        sent = json.dumps(self.seen[-1]["messages"])
        self.assertNotIn("isn't answering", sent)
        self.assertEqual(chats[-1]["source"], "engine_down")

    def test_status_and_restart_endpoints(self) -> None:
        code, _, out = server.dispatch_http_request(self.h, "GET", "/api/ai/status", b"")
        self.assertEqual(code, 200)
        self.assertIn(json.loads(out)["state"], ("ready", "asleep", "not_answering", "model_missing", "restarting"))
        code, _, _ = server.dispatch_http_request(self.h, "POST", "/api/ollama/restart", b"{}",
                                                  headers={"Host": "127.0.0.1:8765"})
        self.assertEqual(code, 403)                                                 # needs the page's session key


if __name__ == "__main__":
    unittest.main()
