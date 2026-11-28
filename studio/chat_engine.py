"""How a bot answers in chat (28 Nov 2026 rewrite).

What was wrong before, and what this does instead:
- The streamed chat never switched Qwen's thinking off, so it spent most of a 500-token budget thinking out loud and the
  answer came late, cut short or not at all. Now thinking is off unless Markus asks for it ("Think harder").
- Tools were offered only when a message contained a file word. Now they are always offered and the model decides.
- A tool round used to be a separate, silent call and the reply then arrived in one lump. Now every round streams.
- Only the last 4 messages were remembered. Now the last 16, capped in size.

Everything here talks to the local Ollama only. `stream_chat` is the one place a chat request is built, so the window
size and keep-alive always match the crypto bot (crypto_paper.rules) and Ollama never reloads Qwen between callers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from crypto_paper import rules as R

REPLY_TOKENS = 1500          # room for a full answer (was 500, shared with thinking)
THINK_TOKENS = 4000          # "Think harder": thinking plus the answer
READ_TIMEOUT_S = 180         # longest wait for the next piece; a cold load took ~28 s on 26 Nov
MAX_TOOL_ROUNDS = 4
HISTORY_MESSAGES = 16
HISTORY_CHARS = 12000
TEMPERATURE = 0.6

Event = Dict[str, Any]
StreamFn = Callable[..., Iterator[Tuple[str, Any]]]


class EngineDown(Exception):
    """The AI engine did not answer (not running, frozen, or the model is missing)."""


def stream_chat(base_url: str, model: str, messages: List[Dict[str, Any]], tools: Optional[list] = None,
                think: bool = False, timeout: float = READ_TIMEOUT_S) -> Iterator[Tuple[str, Any]]:
    """One streamed /api/chat call. Yields ("thought", text), ("token", text) and ("tool_calls", list)."""
    body: Dict[str, Any] = {"model": model, "messages": messages, "stream": True, "think": bool(think),
                            "keep_alive": R.KEEP_ALIVE,
                            "options": {"temperature": TEMPERATURE, "num_ctx": R.NUM_CTX,
                                        "num_predict": THINK_TOKENS if think else REPLY_TOKENS}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(base_url.rstrip("/") + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise EngineDown(f"the AI engine said HTTP {e.code}" + (" (model not found)" if e.code == 404 else "")) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise EngineDown(f"the AI engine did not answer ({type(e).__name__})") from e
    with resp:
        for line in resp:
            if not line.strip():
                continue
            try:
                chunk = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if chunk.get("error"):
                raise EngineDown(str(chunk["error"]))
            msg = chunk.get("message") or {}
            if msg.get("thinking"):
                yield "thought", msg["thinking"]
            if msg.get("content"):
                yield "token", msg["content"]
            if msg.get("tool_calls"):
                yield "tool_calls", msg["tool_calls"]
            if chunk.get("done"):
                break


def trim_history(history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Last HISTORY_MESSAGES user/assistant turns, newest kept first when over HISTORY_CHARS."""
    keep: List[Dict[str, str]] = []
    total = 0
    for h in reversed(history[-HISTORY_MESSAGES:]):
        role, text = h.get("role"), str(h.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if total + len(text) > HISTORY_CHARS:
            break
        keep.append({"role": role, "content": text})
        total += len(text)
    return list(reversed(keep))


class _ThinkFilter:
    """Some model/Ollama versions put thinking inside the answer as <think>...</think>; move it to the thought panel."""
    def __init__(self) -> None:
        self.inside, self.buf = False, ""

    def feed(self, piece: str) -> List[Tuple[str, str]]:
        self.buf += piece
        out: List[Tuple[str, str]] = []
        while self.buf:
            tag = "</think>" if self.inside else "<think>"
            i = self.buf.find(tag)
            if i >= 0:
                if i:
                    out.append(("thought" if self.inside else "token", self.buf[:i]))
                self.buf, self.inside = self.buf[i + len(tag):], not self.inside
                continue
            keep = next((n for n in range(len(tag) - 1, 0, -1) if self.buf.endswith(tag[:n])), 0)
            text, self.buf = (self.buf[:-keep], self.buf[-keep:]) if keep else (self.buf, "")
            if text:
                out.append(("thought" if self.inside else "token", text))
            break
        return out

    def flush(self) -> List[Tuple[str, str]]:
        text, self.buf = self.buf, ""
        return [("thought" if self.inside else "token", text)] if text else []


def answer(base_url: str, model: str, system: str, history: List[Dict[str, Any]], user_msg: str,
           tools: Optional[list] = None, run_tool: Optional[Callable[[str, Dict[str, Any]], str]] = None,
           describe: Optional[Callable[[str, Dict[str, Any]], str]] = None, think: bool = False,
           stream_fn: StreamFn = stream_chat) -> Iterator[Event]:
    """Events for the page, in order: {"thought"}, {"token"}, {"tool"} ... and last {"final": whole answer}.
    Raises EngineDown if the engine can't be reached before anything was said."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, *trim_history(history),
                                      {"role": "user", "content": user_msg}]
    said: List[str] = []
    for rnd in range(MAX_TOOL_ROUNDS + 1):
        offer = tools if tools and run_tool and rnd < MAX_TOOL_ROUNDS else None
        calls: List[Dict[str, Any]] = []
        text = ""
        filt = _ThinkFilter()
        for kind, val in stream_fn(base_url, model, messages, offer, think):
            if kind == "tool_calls":
                calls.extend(val)
                continue
            parts = filt.feed(val) if kind == "token" else [("thought", val)]
            for k, v in parts:
                if k == "token":
                    text += v
                yield {k: v}
        for k, v in filt.flush():
            if k == "token":
                text += v
            yield {k: v}
        if text.strip():
            said.append(text.strip())
        if not calls:
            break
        if text.strip():
            yield {"token": "\n\n"}
        messages.append({"role": "assistant", "content": text, "tool_calls": calls})
        for c in calls:
            fn = c.get("function") or {}
            name, args = str(fn.get("name", "")), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            yield {"tool": describe(name, args) if describe else name}
            result = run_tool(name, args) if run_tool else json.dumps({"error": "no tools"})
            messages.append({"role": "tool", "content": result, "tool_name": name})
    yield {"final": "\n\n".join(said).strip()}
