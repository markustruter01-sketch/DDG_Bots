"""Safety tests (plan Phase 1, 26 Nov 2026): request lock, blocked list, quarantine and restore.

These never touch the real permissions, proposals or quarantine: every test points
governance at a temporary folder first.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO_ROOT))

from dashboard.server import dispatch_http_request, make_handler  # noqa: E402
from studio import governance  # noqa: E402


class _TempGovernance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ddg_sec_"))
        self.home = self.tmp / "home"
        self.work = self.home / "Desktop" / "DDG" / "work"
        self.work.mkdir(parents=True)
        self._saved = (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home)
        governance.PERMISSIONS_FILE = self.tmp / "data" / "computer_permissions.json"
        governance.PROPOSALS_FILE = self.tmp / "data" / "governance_proposals.json"
        governance.QUARANTINE_ROOT = self.tmp / "quarantine"
        governance._home = lambda: self.home
        governance.save_permissions({"scope": "custom", "custom_paths": [str(self.home)]})

    def tearDown(self) -> None:
        (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBlockedList(_TempGovernance):
    def test_blocked_places_refused_in_every_scope(self) -> None:
        for p in (self.home / "AppData" / "Roaming" / "x", self.home / ".ssh" / "id_ed25519",
                  self.home / ".ollama", self.work / ".git" / "config", self.work / "secrets.pem",
                  self.work / ".env", STUDIO_ROOT / "dashboard" / "server.py", governance.QUARANTINE_ROOT / "a"):
            for scope in ("custom", "full_system"):
                governance.save_permissions({"scope": scope, "custom_paths": [str(self.home)]})
                ok, msg = governance.is_path_safe_and_allowed(p)
                self.assertFalse(ok, f"{p} should be blocked in {scope}")
                self.assertIn("Always blocked", msg)

    def test_parent_of_blocked_place_is_blocked(self) -> None:
        ok, msg = governance.is_path_safe_and_allowed(self.home)
        self.assertFalse(ok)
        ok, msg = governance.is_path_safe_and_allowed(STUDIO_ROOT.parent)
        self.assertFalse(ok)
        self.assertIn("contains", msg)

    def test_ordinary_folder_allowed_only_inside_scope(self) -> None:
        self.assertTrue(governance.is_path_safe_and_allowed(self.work / "old.zip")[0])
        other = self.home / "Desktop" / "DDG" / "other"
        other.mkdir()
        governance.save_permissions({"scope": "custom", "custom_paths": [str(other)]})
        self.assertFalse(governance.is_path_safe_and_allowed(self.work / "old.zip")[0])

    def test_unknown_scope_rejected(self) -> None:
        with self.assertRaises(ValueError):
            governance.save_permissions({"scope": "everything"})


class TestQuarantine(_TempGovernance):
    def test_approve_moves_to_quarantine_and_restore_puts_it_back(self) -> None:
        target = self.work / "old_stuff"
        target.mkdir()
        (target / "a.txt").write_text("hello", encoding="utf-8")
        prop = governance.create_deletion_proposal("Heimdall", str(target), "old")
        self.assertEqual(prop["status"], "pending_markus_approval")
        self.assertEqual(prop["file_count"], 1)
        self.assertIn("checks", prop)
        self.assertNotIn("bot_votes", prop)

        done = governance.markus_resolve_proposal(prop["id"], "approve")
        self.assertEqual(done["status"], "quarantined")
        self.assertFalse(target.exists())
        qpath = Path(done["quarantine_path"])
        self.assertTrue((qpath / "a.txt").exists())
        manifest = json.loads((qpath.parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(manifest["original_path"]).resolve(), target.resolve())

        back = governance.restore_proposal(prop["id"])
        self.assertEqual(back["status"], "restored")
        self.assertEqual((target / "a.txt").read_text(encoding="utf-8"), "hello")

    def test_veto_moves_nothing(self) -> None:
        f = self.work / "keep.txt"
        f.write_text("x", encoding="utf-8")
        prop = governance.create_deletion_proposal("Heimdall", str(f), "test")
        self.assertEqual(governance.markus_resolve_proposal(prop["id"], "veto")["status"], "vetoed")
        self.assertTrue(f.exists())

    def test_restore_refuses_to_overwrite(self) -> None:
        f = self.work / "dup.txt"
        f.write_text("1", encoding="utf-8")
        prop = governance.create_deletion_proposal("Heimdall", str(f), "test")
        governance.markus_resolve_proposal(prop["id"], "approve")
        f.write_text("new", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            governance.restore_proposal(prop["id"])
        self.assertEqual(f.read_text(encoding="utf-8"), "new")

    def test_blocked_target_cannot_be_proposed(self) -> None:
        secret = self.home / ".ssh"
        secret.mkdir()
        with self.assertRaises(PermissionError):
            governance.create_deletion_proposal("Heimdall", str(secret), "nope")


class TestRequestLock(_TempGovernance):
    def setUp(self) -> None:
        super().setUp()
        footage = self.tmp / "footage"
        for sub in ("01_Raw_Inbox", "03_Ready_For_Review", "04_Approved_Exports"):
            (footage / sub).mkdir(parents=True)
        self.h = make_handler(STUDIO_ROOT, footage)
        self.body = json.dumps({"scope": "full_system"}).encode("utf-8")

    def test_change_without_token_refused(self) -> None:
        code, _, _ = dispatch_http_request(self.h, "POST", "/api/governance/permissions", self.body,
                                           headers={"Host": "127.0.0.1:8765"})
        self.assertEqual(code, 403)
        self.assertEqual(governance.load_permissions()["scope"], "custom")

    def test_change_from_other_website_refused(self) -> None:
        code, _, _ = dispatch_http_request(self.h, "POST", "/api/governance/permissions", self.body,
                                           headers={"Host": "127.0.0.1:8765", "Origin": "https://evil.example",
                                                    "X-DDG-Token": self.h.token})
        self.assertEqual(code, 403)

    def test_wrong_host_refused_for_reads_too(self) -> None:
        code, _, _ = dispatch_http_request(self.h, "GET", "/api/bots", headers={"Host": "evil.example:8765"})
        self.assertEqual(code, 403)

    def test_dashboard_change_accepted(self) -> None:
        code, _, body = dispatch_http_request(self.h, "POST", "/api/governance/permissions",
                                              json.dumps({"scope": "ddg_workspace"}).encode("utf-8"))
        self.assertEqual(code, 200, body)
        self.assertEqual(governance.load_permissions()["scope"], "ddg_workspace")

    def test_page_carries_token_and_health_answers(self) -> None:
        code, hdrs, page = dispatch_http_request(self.h, "GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(self.h.token.encode("utf-8"), page)
        self.assertNotIn(b"__DDG_SESSION_TOKEN__", page)
        self.assertEqual(hdrs.get("x-frame-options"), "DENY")
        code, _, body = dispatch_http_request(self.h, "GET", "/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_crypto_buttons_need_token_and_a_running_bot(self) -> None:
        body = json.dumps({"action": "reset", "account": "all"}).encode("utf-8")
        code, _, _ = dispatch_http_request(self.h, "POST", "/api/crypto/control", body, headers={"Host": "127.0.0.1:8765"})
        self.assertEqual(code, 403)
        if not (STUDIO_ROOT / "data" / "crypto" / "state.json").exists():
            code, _, _ = dispatch_http_request(self.h, "POST", "/api/crypto/control", body)
            self.assertEqual(code, 409)                                 # bot not running: nothing queued for later

    def test_propose_endpoint_works(self) -> None:
        f = self.work / "old.log"
        f.write_text("x", encoding="utf-8")
        code, _, body = dispatch_http_request(self.h, "POST", "/api/governance/propose",
                                              json.dumps({"bot_name": "Heimdall", "target_path": str(f), "reason": "old"}).encode("utf-8"))
        self.assertEqual(code, 201, body)


class TestHonestPrompts(unittest.TestCase):
    def test_no_false_access_claims(self) -> None:
        src = (STUDIO_ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        for phrase in ("FULL OPERATIONAL ACCESS", "FULL READ AND WRITE ACCESS", "Never say 'I cannot access your files'",
                       "FORBIDDEN STATEMENTS", "Qwen3:8B active at A$0"):
            self.assertNotIn(phrase, src)
        self.assertIn("WHAT YOU CANNOT DO:", src)


if __name__ == "__main__":
    unittest.main()
