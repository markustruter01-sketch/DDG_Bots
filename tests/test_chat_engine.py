"""The chat engine (studio/chat_engine.py): streaming, tools always offered, thinking kept out of the answer."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crypto_paper import rules as R  # noqa: E402
from studio import chat_engine as E  # noqa: E402


def scripted(*rounds):
    """A fake stream: each call returns the next round's list of (kind, value)."""
    seen = []
    it = iter(rounds)

    def fn(base_url, model, messages, tools, think):
        seen.append({"messages": [dict(m) for m in messages], "tools": tools, "think": think})
        yield from next(it)
    return fn, seen


class TestAnswer(unittest.TestCase):
    def test_plain_answer_streams_tokens_then_final(self) -> None:
        fn, seen = scripted([("token", "Hel"), ("token", "lo")])
        evs = list(E.answer("u", "m", "SYS", [], "hi", tools=[{"x": 1}], run_tool=lambda n, a: "{}", stream_fn=fn))
        self.assertEqual([e for e in evs if "token" in e], [{"token": "Hel"}, {"token": "lo"}])
        self.assertEqual(evs[-1], {"final": "Hello"})
        self.assertEqual(seen[0]["tools"], [{"x": 1}])          # tools offered on a plain question too (28 Nov)
        self.assertFalse(seen[0]["think"])

    def test_tool_round_runs_tool_and_continues(self) -> None:
        call = [{"function": {"name": "crypto_status", "arguments": {}}}]
        fn, seen = scripted([("tool_calls", call)], [("token", "Qwen is up 0.1%.")])
        ran = []
        evs = list(E.answer("u", "m", "SYS", [], "how's crypto?", tools=[{}],
                            run_tool=lambda n, a: (ran.append(n), json.dumps({"qwen": 100135.95}))[1],
                            describe=lambda n, a: "Reading the crypto bot", stream_fn=fn))
        self.assertEqual(ran, ["crypto_status"])
        self.assertIn({"tool": "Reading the crypto bot"}, evs)
        self.assertEqual(evs[-1], {"final": "Qwen is up 0.1%."})
        second = seen[1]["messages"]
        self.assertEqual(second[-1]["role"], "tool")
        self.assertIn("100135.95", second[-1]["content"])

    def test_tools_stop_after_max_rounds(self) -> None:
        call = [{"function": {"name": "pc_look", "arguments": '{"path": "C:\\\\"}'}}]
        rounds = [[("tool_calls", call)]] * E.MAX_TOOL_ROUNDS + [[("token", "done")]]
        fn, seen = scripted(*rounds)
        evs = list(E.answer("u", "m", "S", [], "q", tools=[{}], run_tool=lambda n, a: "{}", stream_fn=fn))
        self.assertIsNone(seen[-1]["tools"])                    # last round: no tools, so it must answer
        self.assertEqual(evs[-1], {"final": "done"})

    def test_think_tags_in_the_answer_go_to_the_thought_panel(self) -> None:
        fn, _ = scripted([("token", "<thi"), ("token", "nk>pondering</th"), ("token", "ink>Answer.")])
        evs = list(E.answer("u", "m", "S", [], "q", stream_fn=fn))
        self.assertEqual("".join(e.get("thought", "") for e in evs), "pondering")
        self.assertEqual(evs[-1], {"final": "Answer."})

    def test_history_is_trimmed_newest_kept(self) -> None:
        hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(40)]
        out = E.trim_history(hist)
        self.assertEqual(len(out), E.HISTORY_MESSAGES)
        self.assertEqual(out[-1]["content"], "m39")
        big = [{"role": "user", "content": "x" * (E.HISTORY_CHARS - 10)}, {"role": "assistant", "content": "y" * 50}]
        self.assertEqual(E.trim_history(big), [{"role": "assistant", "content": "y" * 50}])


class FakeOllamaChat:
    """Answers /api/chat with a stream of lines, and records the request."""
    def __init__(self, lines, status=200):
        self.lines, self.status, self.seen = lines, status, []
        owner = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                owner.seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(owner.status)
                self.end_headers()
                for ln in owner.lines:
                    self.wfile.write((json.dumps(ln) + "\n").encode())
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()


class TestStreamChat(unittest.TestCase):
    def test_request_shape_and_stream(self) -> None:
        o = FakeOllamaChat([{"message": {"content": "Hi"}}, {"message": {"content": " there"}}, {"done": True}])
        try:
            got = list(E.stream_chat(o.url, "qwen3:8b", [{"role": "user", "content": "x"}], tools=[{"t": 1}]))
        finally:
            o.close()
        self.assertEqual(got, [("token", "Hi"), ("token", " there")])
        req = o.seen[0]
        self.assertEqual((req["stream"], req["think"], req["keep_alive"]), (True, False, R.KEEP_ALIVE))
        self.assertEqual(req["options"]["num_ctx"], R.NUM_CTX)              # same as the crypto bot: no reloads
        self.assertEqual(req["options"]["num_predict"], E.REPLY_TOKENS)
        self.assertEqual(req["tools"], [{"t": 1}])

    def test_missing_model_is_engine_down(self) -> None:
        o = FakeOllamaChat([], status=404)
        try:
            with self.assertRaises(E.EngineDown) as cm:
                list(E.stream_chat(o.url, "qwen3:8b", []))
        finally:
            o.close()
        self.assertIn("model not found", str(cm.exception))

    def test_nothing_listening_is_engine_down(self) -> None:
        with self.assertRaises(E.EngineDown):
            list(E.stream_chat("http://127.0.0.1:9", "qwen3:8b", [], timeout=2))


if __name__ == "__main__":
    unittest.main()
