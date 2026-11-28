"""The guardian (studio/guardian.py): starts, checks and heals the studio, the crypto bot and the AI engine."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import guardian as G  # noqa: E402


class FakePC(G.System):
    """Scripted answers: ollama_up / model_present / probe_ok / studio_up / crypto_age."""
    def __init__(self, ollama_up=True, model_present=True, probe_ok=True, studio_up=True, crypto_age=5.0,
                 last_ai=None, gaming=False):
        self.ollama_up, self.model_present, self.probe_ok = ollama_up, model_present, probe_ok
        self.studio_up, self.age, self.last_ai, self.busy = studio_up, crypto_age, last_ai, gaming
        self.ran, self.spawned, self.probes = [], [], 0
        self.http = self._http
        self.run = self._run
        self.spawn = self._spawn
        self.sleep = lambda s: None
        self.now = lambda: datetime(2026, 11, 28, 12, 0, tzinfo=G.AEST)
        self.gaming = lambda: (self.busy, "Paused: active process detected (Wow.exe)" if self.busy else "")
        self.crypto_state = lambda: ({"last_decision": {"at": self.last_ai.isoformat(), "missed": False}}
                                     if self.last_ai else {"last_decision": {"at": "2026-11-28T01:00:00+10:00", "missed": True}})
        self.crypto_age_s = lambda: self.age

    def _http(self, url, body=None, timeout=10):
        if url.endswith("/api/tags"):
            if not self.ollama_up:
                return None, None
            return 200, {"models": [{"name": "qwen3:8b"}] if self.model_present else []}
        if url.endswith("/api/generate"):
            self.probes += 1
            return (200, {"response": "OK"}) if self.probe_ok else (None, None)
        if url.endswith("/api/health"):
            return (200, {"ok": True}) if self.studio_up else (None, None)
        return None, None

    def _run(self, cmd, timeout=30):
        self.ran.append(cmd)
        return ""

    def _spawn(self, cmd, log_name, env=None):
        self.spawned.append((cmd, log_name, dict(env or {})))
        if log_name == "ollama.log":        # a fresh engine started with the right folder finds the model
            self.ollama_up = True
            self.model_present = (env or {}).get("OLLAMA_MODELS") == G.ollama_conf()["models_dir"]
            self.probe_ok = True
        if log_name == "server.log":
            self.studio_up = True
        return True


class TestGuardian(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.old = (G.LOGS, G.GUARD_STATE)
        G.LOGS, G.GUARD_STATE = self.tmp, self.tmp / "guardian_state.json"

    def tearDown(self) -> None:
        G.LOGS, G.GUARD_STATE = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def logged(self) -> str:
        p = self.tmp / "watchdog.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def test_frozen_engine_is_restarted_with_the_model_folder(self) -> None:
        pc = FakePC(ollama_up=False)
        out = G.check(pc)
        self.assertEqual(out["ai"], "restarted (not answering)")
        (cmd, log_name, env), = [s for s in pc.spawned if s[1] == "ollama.log"]
        self.assertEqual(cmd[-1], "serve")
        self.assertEqual(env["OLLAMA_MODELS"], G.ollama_conf()["models_dir"])     # 28 Nov: Qwen lives on F:
        self.assertIn("back up", self.logged())

    def test_engine_without_the_model_is_restarted(self) -> None:
        pc = FakePC(model_present=False)
        self.assertEqual(G.check(pc)["ai"], "restarted (model missing)")
        self.assertIn("can't find", self.logged())

    def test_recent_good_crypto_answer_means_no_test(self) -> None:
        pc = FakePC(last_ai=datetime(2026, 11, 28, 11, 50, tzinfo=G.AEST))
        self.assertTrue(G.check(pc)["ai"].startswith("ok"))
        self.assertEqual(pc.probes, 0)

    def test_two_failed_tests_in_a_row_restart_the_engine(self) -> None:
        pc = FakePC(probe_ok=False)
        self.assertTrue(G.check(pc)["ai"].startswith("slow"))                      # one bad test: wait
        self.assertEqual([s for s in pc.spawned if s[1] == "ollama.log"], [])
        self.assertEqual(G.check(pc)["ai"], "restarted (frozen)")                  # second in a row: restart
        self.assertEqual(G._guard_state()["probe_fails"], 0)

    def test_a_good_test_resets_the_count(self) -> None:
        pc = FakePC(probe_ok=False)
        G.check(pc)
        pc.probe_ok = True
        G.check(pc)
        pc.probe_ok = False
        self.assertTrue(G.check(pc)["ai"].startswith("slow"))

    def test_no_test_while_gaming(self) -> None:
        pc = FakePC(probe_ok=False, gaming=True)
        self.assertTrue(G.check(pc)["ai"].startswith("not tested"))
        self.assertEqual(pc.probes, 0)

    def test_dead_dashboard_and_stale_crypto_bot_are_started(self) -> None:
        pc = FakePC(studio_up=False, crypto_age=999, last_ai=datetime(2026, 11, 28, 11, 55, tzinfo=G.AEST))
        out = G.check(pc)
        self.assertEqual((out["studio"], out["crypto"]), ("restarted", "started"))
        logs = [s[1] for s in pc.spawned]
        self.assertEqual(logs, ["server.log", "crypto.log"])
        self.assertIn("crypto_paper.runner", pc.spawned[1][0])

    def test_start_from_nothing_starts_engine_first(self) -> None:
        pc = FakePC(ollama_up=False, studio_up=False, crypto_age=None)
        self.assertTrue(G.start(pc))
        self.assertEqual([s[1] for s in pc.spawned], ["ollama.log", "server.log", "crypto.log"])

    def test_start_leaves_running_things_alone(self) -> None:
        pc = FakePC()
        self.assertTrue(G.start(pc))
        self.assertEqual(pc.spawned, [])

    def test_model_name_match(self) -> None:
        self.assertTrue(G.has_model(["qwen3:8b", "qwen3-vl:4b"], "qwen3:8b"))
        self.assertFalse(G.has_model(["qwen3:4b"], "qwen3:8b"))
        self.assertTrue(G.has_model(["llama3:latest"], "llama3"))

    def test_big_log_is_rotated(self) -> None:
        p = self.tmp / "server.log"
        p.write_bytes(b"x" * (G.LOG_MAX_BYTES + 1))
        G.rotate(p)
        self.assertFalse(p.exists())
        self.assertTrue((self.tmp / "server.log.1").exists())


if __name__ == "__main__":
    unittest.main()
