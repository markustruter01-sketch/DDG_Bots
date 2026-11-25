"""VRAM Baton & UE5/Gaming smart-pause manager for single-GPU (RTX 3070 Ti 8GB) safety."""

from __future__ import annotations

import gc
import json
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Iterable


_GPU_LOCK = threading.Lock()


def unload_ollama(base_url: str = "http://127.0.0.1:11434", model: str | None = None) -> bool:
    """Force Ollama to immediately evict model weights from VRAM (keep_alive=0)."""
    if not model:
        return True
    payload = json.dumps({"model": model, "keep_alive": 0}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def flush_torch_vram() -> None:
    """Release PyTorch cached VRAM allocations back to Windows WDDM/CUDA."""
    gc.collect()
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except ImportError:
        pass


def query_vram_used_mb() -> int | None:
    """Return current GPU VRAM usage in MiB via nvidia-smi without flashing console windows."""
    try:
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        first = out.strip().splitlines()[0].strip()
        return int(first)
    except Exception:
        return None


def get_running_processes() -> set[str]:
    """Return lowercase executable names currently running on Windows without flashing console windows."""
    try:
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        names: set[str] = set()
        for line in out.splitlines():
            line = line.strip()
            if not line or not line.startswith('"'):
                continue
            proc = line.split('"', 2)[1].lower()
            names.add(proc)
        return names
    except Exception:
        return set()


def is_gpu_busy_for_user(
    paused_processes: Iterable[str] = (
        "UnrealEditor.exe",
        "UnrealEditor-Win64-Shipping.exe",
        "Streamlabs Desktop.exe",
    ),
    vram_threshold_mb: int = 2500,
) -> tuple[bool, str]:
    """Check whether Markus is actively using Unreal Engine, Streamlabs, or heavy GPU VRAM."""
    running = get_running_processes()
    for target in paused_processes:
        if target.lower() in running:
            return True, f"Paused: active process detected ({target})"

    used_mb = query_vram_used_mb()
    if used_mb is not None and used_mb >= vram_threshold_mb:
        return True, f"Paused: GPU VRAM already busy ({used_mb} MiB >= {vram_threshold_mb} MiB)"

    return False, "GPU available"


class VramBaton:
    """Context manager serializing GPU stages and flushing VRAM between them."""

    def __init__(
        self,
        stage_name: str,
        ollama_url: str = "http://127.0.0.1:11434",
        ollama_model: str | None = None,
    ) -> None:
        self.stage_name = stage_name
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model

    def __enter__(self) -> "VramBaton":
        _GPU_LOCK.acquire()
        flush_torch_vram()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self.ollama_model:
                unload_ollama(self.ollama_url, self.ollama_model)
            flush_torch_vram()
        finally:
            _GPU_LOCK.release()
