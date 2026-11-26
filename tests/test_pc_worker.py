"""PC worker tests (plan Phase 2): look, plan, approve, undo. Uses only temporary folders."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO_ROOT))

from dashboard.server import dispatch_http_request, make_handler  # noqa: E402
from studio import governance, pc_worker  # noqa: E402

OLD = time.time() - 40 * 86400


class _Temp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ddg_pcw_"))
        self.home = self.tmp / "home"
        self.dl = self.home / "Downloads"
        self.arc = self.home / "Archive"
        self.dl.mkdir(parents=True)
        self.arc.mkdir()
        self._g = (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home)
        self._p = pc_worker.PLANS_FILE
        governance.PERMISSIONS_FILE = self.tmp / "data" / "perm.json"
        governance.PROPOSALS_FILE = self.tmp / "data" / "props.json"
        governance.QUARANTINE_ROOT = self.tmp / "quarantine"
        governance._home = lambda: self.home
        pc_worker.PLANS_FILE = self.tmp / "data" / "plans.json"
        governance.save_permissions({"scope": "custom", "custom_paths": [str(self.dl), str(self.arc)]})

    def tearDown(self) -> None:
        (governance.PERMISSIONS_FILE, governance.PROPOSALS_FILE, governance.QUARANTINE_ROOT, governance._home) = self._g
        pc_worker.PLANS_FILE = self._p
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, rel: str, data: bytes = b"x", old: bool = True) -> Path:
        p = self.dl / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        if old:
            os.utime(p, (OLD, OLD))
        return p


class TestLooking(_Temp):
    def test_list_sizes_search(self) -> None:
        self.make("a.zip", b"1" * 3000)
        self.make("sub/b.exe", b"2" * 10)
        listed = pc_worker.list_dir(str(self.dl))
        self.assertEqual(sorted(i["name"] for i in listed["items"]), ["a.zip", "sub"])
        sizes = pc_worker.folder_sizes(str(self.dl))
        self.assertEqual(sizes["items"][0]["name"], "a.zip")
        self.assertEqual(len(pc_worker.search(str(self.dl), "*.exe")["items"]), 1)
        self.assertEqual(len(pc_worker.search(str(self.dl), "*", older_than_days=30)["items"]), 2)

    def test_duplicates_by_content(self) -> None:
        self.make("one.mp4", b"same" * 400000)
        self.make("copy/one (1).mp4", b"same" * 400000)
        self.make("other.mp4", b"diff" * 400000)
        dup = pc_worker.find_duplicates(str(self.dl), min_size_mb=1)
        self.assertEqual(len(dup["groups"]), 1)
        self.assertEqual(len(dup["groups"][0]["copies"]), 2)

    def test_looking_outside_scope_refused(self) -> None:
        with self.assertRaises(pc_worker.WorkerError):
            pc_worker.list_dir(str(self.home / "AppData"))
        with self.assertRaises(pc_worker.WorkerError):
            pc_worker.list_dir(str(self.home))


class TestPlans(_Temp):
    def test_plan_approve_undo_round_trip(self) -> None:
        a = self.make("setup.exe", b"a" * 100)
        b = self.make("dup.mp4", b"b" * 50)
        plan = pc_worker.create_plan("Heimdall", "Tidy Downloads", [
            {"src": str(a), "dest": str(self.arc / "Installers" / "setup.exe")},
            {"src": str(b), "dest": "QUARANTINE"},
        ])
        self.assertEqual(plan["summary"]["will_move"], 2)
        self.assertEqual(plan["summary"]["bytes"], 150)
        self.assertTrue(a.exists(), "creating a plan must not move anything")

        done = pc_worker.approve_plan(plan["id"])
        self.assertEqual(done["status"], "done")
        self.assertFalse(a.exists())
        self.assertTrue((self.arc / "Installers" / "setup.exe").exists())
        self.assertEqual(len(done["journal"]), 2)
        self.assertTrue(any(governance.QUARANTINE_ROOT.rglob("*dup.mp4")))

        back = pc_worker.undo_plan(plan["id"])
        self.assertEqual(back["status"], "undone")
        self.assertEqual(a.read_bytes(), b"a" * 100)
        self.assertEqual(b.read_bytes(), b"b" * 50)

    def test_blocked_and_bad_moves_are_flagged_not_run(self) -> None:
        a = self.make("x.txt")
        (self.arc / "taken.txt").write_text("keep", encoding="utf-8")
        secret = self.dl / ".git" / "config"
        secret.parent.mkdir()
        secret.write_text("c", encoding="utf-8")
        plan = pc_worker.create_plan("Markus", "bad", [
            {"src": str(a), "dest": str(self.arc / "taken.txt")},            # would overwrite
            {"src": str(secret), "dest": "QUARANTINE"},                       # blocked place
            {"src": str(self.dl / "missing.txt"), "dest": "QUARANTINE"},     # not there
            {"src": str(a), "dest": str(self.home / "Desktop" / "x.txt")},  # outside scope (and listed twice)
        ])
        self.assertEqual(plan["summary"]["will_move"], 0)
        self.assertEqual(plan["summary"]["blocked"], 4)
        pc_worker.approve_plan(plan["id"])
        self.assertTrue(a.exists())
        self.assertEqual((self.arc / "taken.txt").read_text(encoding="utf-8"), "keep")

    def test_recent_file_warns(self) -> None:
        fresh = self.make("today.docx", old=False)
        plan = pc_worker.create_plan("Markus", "warn", [{"src": str(fresh), "dest": "QUARANTINE"}])
        self.assertEqual(plan["moves"][0]["status"], "warn")

    def test_undo_never_overwrites(self) -> None:
        a = self.make("a.txt", b"old")
        plan = pc_worker.create_plan("Markus", "t", [{"src": str(a), "dest": str(self.arc / "a.txt")}])
        pc_worker.approve_plan(plan["id"])
        a.write_bytes(b"new")
        back = pc_worker.undo_plan(plan["id"])
        self.assertEqual(back["status"], "partly_undone")
        self.assertEqual(a.read_bytes(), b"new")
        self.assertTrue((self.arc / "a.txt").exists())

    def test_reject_moves_nothing_and_cannot_run_twice(self) -> None:
        a = self.make("a.txt")
        plan = pc_worker.create_plan("Markus", "t", [{"src": str(a), "dest": "QUARANTINE"}])
        pc_worker.reject_plan(plan["id"])
        self.assertTrue(a.exists())
        with self.assertRaises(pc_worker.WorkerError):
            pc_worker.approve_plan(plan["id"])


class TestRoutes(_Temp):
    def test_routes_need_token_and_work_with_it(self) -> None:
        footage = self.tmp / "footage"
        for sub in ("01_Raw_Inbox", "03_Ready_For_Review", "04_Approved_Exports"):
            (footage / sub).mkdir(parents=True)
        h = make_handler(STUDIO_ROOT, footage)
        a = self.make("a.txt")
        body = json.dumps({"proposer": "Heimdall", "title": "t", "moves": [{"src": str(a), "dest": "QUARANTINE"}]}).encode()
        code, _, _ = dispatch_http_request(h, "POST", "/api/pc/plans", body, headers={"Host": "127.0.0.1:8765"})
        self.assertEqual(code, 403)
        code, _, out = dispatch_http_request(h, "POST", "/api/pc/plans", body)
        self.assertEqual(code, 200, out)
        pid = json.loads(out)["plan"]["id"]
        code, _, out = dispatch_http_request(h, "POST", f"/api/pc/plans/{pid}/approve", b"{}")
        self.assertEqual(json.loads(out)["plan"]["status"], "done")
        code, _, out = dispatch_http_request(h, "POST", "/api/pc/list", json.dumps({"path": str(self.home / ".ssh")}).encode())
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
