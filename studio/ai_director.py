"""Local Ollama AI Director (qwen3:8b text + qwen3-vl:4b vision) with A$0 offline deterministic fallback."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .models import MentionItem, Transcript
from .vram_baton import VramBaton


class OllamaClient:
    """Zero-cost local Ollama HTTP client strictly bound to 127.0.0.1 with keep_alive=0."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        text_model: str = "qwen3:8b",
        vision_model: str = "qwen3-vl:4b",
        timeout_s: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.text_model = text_model
        self.vision_model = vision_model
        self.timeout_s = timeout_s

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def chat_json(self, system_prompt: str, user_prompt: str, model: str | None = None) -> dict[str, Any]:
        target_model = model or self.text_model
        payload = json.dumps(
            {
                "model": target_model,
                "stream": False,
                "think": False,
                "format": "json",
                "keep_alive": 0,
                "options": {"temperature": 0.2},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with VramBaton("ollama_chat_json", ollama_url=self.base_url, ollama_model=target_model):
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        content = raw.get("message", {}).get("content", "{}")
        return json.loads(content)

    def warmup(self, model: str | None = None) -> bool:
        """Load the chat model into VRAM now (and keep it for 10 min) so the first reply is instant."""
        target_model = model or self.text_model
        payload = json.dumps({"model": target_model, "prompt": "", "keep_alive": "10m", "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate", data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status == 200
        except Exception:
            return False

    @staticmethod
    def _messages(system_prompt: str, user_prompt: str, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
        msgs = [{"role": "system", "content": system_prompt}]
        for h in history or []:
            if h.get("role") in ("user", "assistant") and str(h.get("content", "")).strip():
                msgs.append({"role": h["role"], "content": str(h["content"])})
        msgs.append({"role": "user", "content": user_prompt})
        return msgs

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Fast interactive chat with thinking disabled and 10m keep_alive so replies arrive in 1-3s."""
        target_model = model or self.text_model
        payload = json.dumps(
            {
                "model": target_model,
                "stream": False,
                "think": False,
                "keep_alive": "10m",
                "options": {"temperature": 0.4, "num_predict": 500},
                "messages": self._messages(system_prompt, user_prompt, history),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return str(raw.get("message", {}).get("content", "")).strip()

    def chat_raw(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                 model: str | None = None) -> dict[str, Any]:
        """One non-streamed chat call; returns the reply message (may carry tool_calls)."""
        body: dict[str, Any] = {"model": model or self.text_model, "stream": False, "think": False, "keep_alive": "10m",
                                "options": {"temperature": 0.2, "num_predict": 700}, "messages": messages}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(f"{self.base_url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return raw.get("message", {}) or {}

    def chat_text_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        history: list[dict[str, str]] | None = None,
        include_thinking: bool = True,
    ):
        """Token generator yielding both thinking/reasoning and final response tokens as dicts."""
        target_model = model or self.text_model
        payload = json.dumps(
            {
                "model": target_model,
                "stream": True,
                "keep_alive": "10m",
                "options": {"temperature": 0.4, "num_predict": 500},
                "messages": self._messages(system_prompt, user_prompt, history),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            for line in resp:
                if line:
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                        msg = chunk.get("message", {})
                        # In Qwen3 / modern Ollama, reasoning appears in msg["thinking"] or msg["thought"] or delimited in content
                        thought_piece = msg.get("thinking") or msg.get("thought") or ""
                        content_piece = msg.get("content") or ""
                        if thought_piece:
                            yield {"thought": thought_piece}
                        if content_piece:
                            yield {"token": content_piece}
                    except Exception:
                        pass

    def inspect_frame(self, image_path: str | Path, prompt: str) -> dict[str, Any]:
        """Run local Vision QA (qwen3-vl:4b) with thinking disabled per 2026 VLM best practices."""
        import base64

        img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        payload = json.dumps(
            {
                "model": self.vision_model,
                "stream": False,
                "think": False,
                "format": "json",
                "keep_alive": 0,
                "options": {"temperature": 0.1},
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [img_b64],
                    }
                ],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with VramBaton("ollama_vision_qa", ollama_url=self.base_url, ollama_model=self.vision_model):
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        content = raw.get("message", {}).get("content", "{}")
        return json.loads(content)


def generate_social_copy(
    job_id: str,
    transcript: Transcript,
    mentions: list[MentionItem],
    *,
    offline: bool = False,
    ollama: OllamaClient | None = None,
) -> dict[str, Any]:
    """Draft YouTube, X (@DDGCompany), and Instagram copy obeying DDG voice & AI disclosure rules."""
    mention_names = [m.official_name for m in mentions if not m.is_private_business]
    text_snippet = transcript.full_text()[:2500]

    if not offline and ollama is not None and ollama.is_available():
        sys_prompt = (
            "You are DDG's local Marketing Director. Voice: warm, plain-spoken first-person creator "
            "(Digital Dynamics). RULES: ZERO emojis, NEVER invent numbers or stats, NEVER use 'reshoot', "
            "always end YouTube description with 'Made with AI tools.'. Return JSON with keys: "
            "youtube_title, youtube_description, x_post, instagram_caption, chapters."
        )
        user_prompt = (
            f"Job: {job_id}\nMentioned tools/brands: {mention_names}\n"
            f"Transcript excerpt:\n{text_snippet}"
        )
        try:
            res = ollama.chat_json(sys_prompt, user_prompt)
            desc = str(res.get("youtube_description", ""))
            if "Made with AI tools." not in desc:
                desc = (desc + "\n\nMade with AI tools.").strip()
            res["youtube_description"] = desc
            res["youtube_synthetic_flag"] = False
            res["source"] = f"ollama:{ollama.text_model}"
            return res
        except Exception:
            pass

    tools_line = f"Tools mentioned: {', '.join(mention_names)}." if mention_names else ""
    yt_desc = (
        f"Building Digital Dynamics in public.\n\n"
        f"{tools_line}\n\n"
        "Made with AI tools."
    ).strip()
    return {
        "youtube_title": f"Building Digital Dynamics in Public | {job_id}",
        "youtube_description": yt_desc,
        "youtube_synthetic_flag": False,
        "x_post": (
            "Another build session at Digital Dynamics. Keeping the edit clean, checking the numbers, "
            "and shipping step by step."
        ),
        "instagram_caption": "Behind the scenes building Digital Dynamics.",
        "chapters": [{"time": "00:00", "title": "Opening"}],
        "source": "offline_deterministic",
    }
