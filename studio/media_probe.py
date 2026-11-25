"""Media probing, G1 source resolution/bitrate verification, and SHA256 helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .models import GateResult


def _parse_fps(rate_str: str) -> float:
    if not rate_str or rate_str == "0/0":
        return 0.0
    if "/" in rate_str:
        num, den = rate_str.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    return float(rate_str)


def probe_media(path: str | Path) -> dict[str, Any]:
    """Run ffprobe on a video/audio file and return parsed metadata."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Media file not found: {target}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(target),
    ]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE, timeout=90)
    raw = json.loads(out)

    video_stream = next(
        (s for s in raw.get("streams", []) if s.get("codec_type") == "video"), None
    )
    audio_stream = next(
        (s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    fmt = raw.get("format", {})

    duration_s = float(fmt.get("duration") or (video_stream or {}).get("duration") or 0.0)
    total_bitrate = int(fmt.get("bit_rate") or 0)
    video_bitrate = int((video_stream or {}).get("bit_rate") or total_bitrate or 0)

    return {
        "path": str(target),
        "format_name": fmt.get("format_name", ""),
        "size_bytes": int(fmt.get("size") or target.stat().st_size),
        "duration_s": duration_s,
        "total_bitrate_bps": total_bitrate,
        "video": {
            "present": video_stream is not None,
            "codec": (video_stream or {}).get("codec_name", ""),
            "width": int((video_stream or {}).get("width") or 0),
            "height": int((video_stream or {}).get("height") or 0),
            "fps": round(_parse_fps((video_stream or {}).get("avg_frame_rate", "0/0")), 3),
            "bitrate_bps": video_bitrate,
        },
        "audio": {
            "present": audio_stream is not None,
            "codec": (audio_stream or {}).get("codec_name", ""),
            "sample_rate": int((audio_stream or {}).get("sample_rate") or 0),
            "channels": int((audio_stream or {}).get("channels") or 0),
        },
    }


def check_source_quality(
    probe: dict[str, Any],
    min_width: int = 1920,
    min_height: int = 1080,
    min_fps: float = 59.0,
) -> GateResult:
    """Enforce G1 source resolution (>=1080p) and framerate (>=59fps) rules."""
    v = probe.get("video", {})
    if not v.get("present"):
        return GateResult(
            gate_id="G1_SOURCE",
            name="Source Video Quality (G1)",
            passed=False,
            summary="No video stream detected in source file.",
        )

    w = int(v.get("width", 0))
    h = int(v.get("height", 0))
    fps = float(v.get("fps", 0.0))
    issues: list[str] = []
    if w < min_width or h < min_height:
        issues.append(
            f"Source resolution {w}x{h} is below required {min_width}x{min_height} (flag to Markus before editing)."
        )
    if fps < min_fps:
        issues.append(
            f"Source FPS {fps:.2f} is below required {min_fps:.1f} fps."
        )

    return GateResult(
        gate_id="G1_SOURCE",
        name="Source Video Quality (G1)",
        passed=len(issues) == 0,
        summary=(
            f"Source verified: {w}x{h} @ {fps:.2f} fps, {probe.get('duration_s', 0.0):.2f}s"
            if not issues
            else "; ".join(issues)
        ),
        details=issues,
    )


def check_master_bitrate(
    probe: dict[str, Any],
    min_bps: int = 8_000_000,
    max_bps: int = 12_000_000,
) -> tuple[bool, str]:
    """Verify rendered master meets 8-12 Mbps floor/target (allows slight VBR ceiling up to 16 Mbps)."""
    v_bps = int(probe.get("video", {}).get("bitrate_bps") or probe.get("total_bitrate_bps") or 0)
    mbps = v_bps / 1_000_000.0
    if v_bps < min_bps:
        return False, f"Master bitrate {mbps:.2f} Mbps is below {min_bps / 1e6:.1f} Mbps floor (risks pixelation)."
    if v_bps > max_bps * 2.2:
        return False, f"Master bitrate {mbps:.2f} Mbps exceeds expected VBR ceiling."
    return True, f"Master bitrate {mbps:.2f} Mbps within target range."


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA256 hex digest of a file for PC delivery verification."""
    h = hashlib.sha256()
    with open(Path(path), "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
