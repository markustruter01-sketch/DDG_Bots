"""Audio analysis, 10 ms RMS silence snapping (G10), swear-only static censor (G2/G5b), and loudness verification."""

from __future__ import annotations

import json
import math
import random
import re
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

from .models import CutProposal, GateResult, Transcript


# Strictly 'fuck' and 'shit' and their inflected/compound forms ONLY (Markus, 24 Nov 2026).
# Never matches words like 'mishit', 'cattle dog', 'damn', 'hell', 'crap', 'ass', etc.
_SWEAR_PATTERN = re.compile(
    r"^(?:"
    r"(?:mother)?fuck(?:er|ers|ing|in|ed|s|wit|wits|head|heads|ery|up|ups|off|face)?"
    r"|"
    r"(?:bull|bat|ape|horse|chicken|dip)?shit(?:s|ty|tier|tiest|ting|ted|head|heads|show|shows|load|loads|storm|storms|bag|bags|post|posts|posting|hole|holes|faced|less)?"
    r")$",
    re.IGNORECASE,
)


def _strip_token(word: str) -> str:
    return re.sub(r"^[^A-Za-z0-9']+|[^A-Za-z0-9']+$", "", word)


def is_allowed_swear_word(word: str) -> bool:
    clean = _strip_token(word)
    if not clean:
        return False
    return bool(_SWEAR_PATTERN.match(clean))


def mask_swear_word(word: str) -> str:
    """Mask swear word for captions (e.g., 'fucking' -> 'f******') preserving punctuation."""
    m = re.match(r"^([^A-Za-z0-9']*)([A-Za-z0-9']+)([^A-Za-z0-9']*)$", word)
    if not m:
        return word
    pre, core, post = m.groups()
    if len(core) <= 1:
        return word
    return f"{pre}{core[0]}{'*' * (len(core) - 1)}{post}"


def detect_swears(transcript: Transcript) -> list[dict[str, Any]]:
    """Return list of swear spans strictly matching fuck/shit forms."""
    spans: list[dict[str, Any]] = []
    for w in transcript.words:
        if is_allowed_swear_word(w.word):
            spans.append(
                {
                    "word": w.word,
                    "masked": mask_swear_word(w.word),
                    "start_s": round(w.start, 4),
                    "end_s": round(w.end, 4),
                }
            )
    return spans


def extract_wav_mono(input_media: str | Path, output_wav: str | Path, sample_rate: int = 48000) -> Path:
    """Extract 16-bit mono PCM WAV via FFmpeg for deterministic 10 ms RMS & sync checks."""
    out = Path(output_wav)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        str(input_media),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(out),
    ]
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {res.stderr[-500:]}")
    return out


def _read_pcm16_mono(wav_path: str | Path) -> tuple[int, list[int]]:
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
            raise ValueError(
                f"Expected 16-bit mono WAV, got {wf.getnchannels()}ch {wf.getsampwidth()*8}-bit"
            )
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    count = len(raw) // 2
    samples = list(struct.unpack(f"<{count}h", raw))
    return sr, samples


def _write_pcm16_mono(wav_path: str | Path, sr: int, samples: list[int]) -> Path:
    out = Path(wav_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    clamped = [max(-32768, min(32767, int(s))) for s in samples]
    raw = struct.pack(f"<{len(clamped)}h", *clamped)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(raw)
    return out


def measure_rms_10ms(wav_path: str | Path) -> list[tuple[float, float]]:
    """Measure RMS level in dBFS across consecutive 10 ms windows."""
    sr, samples = _read_pcm16_mono(wav_path)
    win = max(1, int(round(sr * 0.010)))
    series: list[tuple[float, float]] = []
    for idx in range(0, len(samples), win):
        chunk = samples[idx : idx + win]
        if not chunk:
            continue
        sq_sum = sum(s * s for s in chunk)
        rms = math.sqrt(sq_sum / len(chunk)) / 32768.0
        db = 20.0 * math.log10(max(rms, 1e-6))
        t_s = round(idx / sr, 4)
        series.append((t_s, round(db, 2)))
    return series


def rms_at_time(rms_series: list[tuple[float, float]], target_s: float) -> float:
    if not rms_series:
        return -120.0
    idx = min(len(rms_series) - 1, max(0, int(round(target_s / 0.010))))
    return rms_series[idx][1]


def find_nearest_silence_boundary(
    rms_series: list[tuple[float, float]],
    target_s: float,
    search_window_s: float = 0.8,
    pad_ms: int = 120,
    noise_floor_db: float = -42.0,
) -> tuple[float, float]:
    """Snap a cut boundary strictly inside 10 ms measured silence with 100-150 ms padding (G10)."""
    if not rms_series:
        return round(target_s, 3), -120.0

    pad_s = max(0.10, min(0.15, pad_ms / 1000.0))
    candidates = [
        (t, db)
        for (t, db) in rms_series
        if (target_s - search_window_s) <= t <= (target_s + search_window_s)
    ]
    if not candidates:
        candidates = rms_series

    # Group contiguous silent 10ms bins
    spans: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for item in candidates:
        if item[1] <= noise_floor_db:
            cur.append(item)
        elif cur:
            spans.append(cur)
            cur = []
    if cur:
        spans.append(cur)

    if not spans:
        # Fallback: pick the absolute quietest 10ms frame in the window
        quietest = min(candidates, key=lambda x: x[1])
        return quietest[0], quietest[1]

    # Pick span closest to target_s that can accommodate padding, else longest silent span
    best_pt: tuple[float, float] | None = None
    best_dist = float("inf")
    for span in spans:
        s_start = span[0][0]
        s_end = span[-1][0]
        span_dur = s_end - s_start
        if span_dur >= 2 * pad_s:
            safe_lo = s_start + pad_s
            safe_hi = s_end - pad_s
            clamped_t = min(safe_hi, max(safe_lo, target_s))
            dist = abs(clamped_t - target_s)
            if dist < best_dist:
                best_dist = dist
                best_pt = (round(clamped_t, 3), rms_at_time(rms_series, clamped_t))

    if best_pt is not None:
        return best_pt

    # Otherwise choose midpoint of the longest quiet span
    longest = max(spans, key=len)
    mid = longest[len(longest) // 2]
    return mid[0], mid[1]


def propose_long_gaps(
    transcript: Transcript,
    rms_series: list[tuple[float, float]],
    min_gap_s: float = 4.0,
    pad_ms: int = 120,
    noise_floor_db: float = -42.0,
) -> list[CutProposal]:
    """Propose ONLY long non-talking spans (>=4 s) for Markus's approval; NEVER cut short pauses."""
    words = sorted(transcript.words, key=lambda w: w.start)
    if len(words) < 2:
        return []

    proposals: list[CutProposal] = []
    idx = 1
    for prev_w, next_w in zip(words, words[1:]):
        raw_gap = next_w.start - prev_w.end
        if raw_gap < min_gap_s:
            continue
        pad_s = max(0.10, min(0.15, pad_ms / 1000.0))
        cut_start, start_db = find_nearest_silence_boundary(
            rms_series, prev_w.end + pad_s, search_window_s=0.5, pad_ms=pad_ms, noise_floor_db=noise_floor_db
        )
        cut_end, end_db = find_nearest_silence_boundary(
            rms_series, next_w.start - pad_s, search_window_s=0.5, pad_ms=pad_ms, noise_floor_db=noise_floor_db
        )
        if cut_end - cut_start >= min_gap_s - 0.5:
            proposals.append(
                CutProposal(
                    id=f"gap_{idx:03d}",
                    start_s=round(cut_start, 3),
                    end_s=round(cut_end, 3),
                    reason=f"Long silence/wait ({raw_gap:.1f}s) between '{prev_w.word}' and '{next_w.word}'",
                    approved=False,
                    is_short_pause=False,
                    start_rms_db=start_db,
                    end_rms_db=end_db,
                )
            )
            idx += 1
    return proposals


def _biquad_coeffs_highpass(sr: float, cutoff_hz: float, q: float = 0.7071) -> tuple[float, float, float, float, float]:
    w0 = 2.0 * math.pi * cutoff_hz / sr
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    b0 = (1.0 + cos_w0) / 2.0
    b1 = -(1.0 + cos_w0)
    b2 = (1.0 + cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def _biquad_coeffs_lowpass(sr: float, cutoff_hz: float, q: float = 0.7071) -> tuple[float, float, float, float, float]:
    w0 = 2.0 * math.pi * cutoff_hz / sr
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    b0 = (1.0 - cos_w0) / 2.0
    b1 = 1.0 - cos_w0
    b2 = (1.0 - cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def _apply_biquad(signal: list[float], coeffs: tuple[float, float, float, float, float]) -> list[float]:
    b0, b1, b2, a1, a2 = coeffs
    x1 = x2 = y1 = y2 = 0.0
    out: list[float] = []
    for x0 in signal:
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, x0
        y2, y1 = y1, y0
        out.append(y0)
    return out


def generate_bandpass_static(
    num_samples: int,
    sr: int,
    low_hz: float = 200.0,
    high_hz: float = 1800.0,
    gain: float = 0.05992,
    seed: int = 42,
) -> list[int]:
    """Generate soft 200-1800 Hz bandpass static noise at exact gain (0.0856 * 0.7 = 0.05992)."""
    rng = random.Random(seed)
    white = [rng.uniform(-1.0, 1.0) for _ in range(num_samples)]
    hp = _apply_biquad(white, _biquad_coeffs_highpass(sr, low_hz))
    bp = _apply_biquad(hp, _biquad_coeffs_lowpass(sr, high_hz))
    peak = max((abs(v) for v in bp), default=1.0) or 1.0
    scale = (gain * 32767.0) / peak
    return [int(round(v * scale)) for v in bp]


def apply_swear_static_censor(
    input_wav: str | Path,
    output_wav: str | Path,
    swear_spans: list[dict[str, Any]],
    gain: float = 0.05992,
    fade_ms: int = 30,
    band_hz: tuple[float, float] = (200.0, 1800.0),
) -> Path:
    """Replace ONLY approved swear spans with soft bandpass static and 30 ms fades; never mute anything else."""
    sr, samples = _read_pcm16_mono(input_wav)
    out_samples = list(samples)
    fade_n = max(1, int(round(sr * (fade_ms / 1000.0))))

    for i, span in enumerate(swear_spans):
        s_idx = max(0, int(round(float(span["start_s"]) * sr)))
        e_idx = min(len(out_samples), int(round(float(span["end_s"]) * sr)))
        if e_idx <= s_idx:
            continue
        length = e_idx - s_idx
        noise = generate_bandpass_static(
            length, sr, low_hz=band_hz[0], high_hz=band_hz[1], gain=gain, seed=100 + i
        )
        local_fade = min(fade_n, max(1, length // 3))
        for j in range(length):
            if j < local_fade:
                w = j / local_fade
            elif j >= length - local_fade:
                w = (length - 1 - j) / local_fade
            else:
                w = 1.0
            orig = out_samples[s_idx + j]
            out_samples[s_idx + j] = int(round((1.0 - w) * orig + w * noise[j]))

    return _write_pcm16_mono(output_wav, sr, out_samples)


def audit_g5b_no_privacy_mutes(
    raw_wav: str | Path,
    processed_wav: str | Path,
    transcript: Transcript,
    swear_spans: list[dict[str, Any]],
    max_drop_db: float = 18.0,
) -> GateResult:
    """Verify Markus's voice has ZERO non-swear privacy mutes or dropouts (G5b)."""
    raw_rms = measure_rms_10ms(raw_wav)
    proc_rms = measure_rms_10ms(processed_wav)
    violations: list[str] = []

    for w in transcript.words:
        # Ignore swear spans
        overlaps_swear = any(
            not (w.end <= float(s["start_s"]) or float(s["end_s"]) <= w.start)
            for s in swear_spans
        )
        if overlaps_swear:
            continue

        start_bin = max(0, int(w.start / 0.010))
        end_bin = min(min(len(raw_rms), len(proc_rms)), max(start_bin + 1, int(w.end / 0.010)))
        if end_bin <= start_bin:
            continue

        raw_peak = max(raw_rms[k][1] for k in range(start_bin, end_bin))
        proc_peak = max(proc_rms[k][1] for k in range(start_bin, end_bin))
        # Only check words that actually had clear voice energy in raw audio
        if raw_peak > -45.0 and (raw_peak - proc_peak) > max_drop_db:
            violations.append(
                f"Non-swear word '{w.word}' ({w.start:.2f}s-{w.end:.2f}s) dropped {raw_peak - proc_peak:.1f} dB "
                f"(raw {raw_peak:.1f} dBFS -> proc {proc_peak:.1f} dBFS)"
            )

    return GateResult(
        gate_id="G5b_AUDIO_CENSOR",
        name="No Non-Swear Privacy Mutes & Swear-Only Static (G5b)",
        passed=len(violations) == 0,
        summary=(
            f"All {len(transcript.words)} words verified: 0 non-swear mutes, {len(swear_spans)} swear static span(s)."
            if not violations
            else f"Detected {len(violations)} illegal non-swear mute/dropout(s)."
        ),
        details=violations,
    )


def compensate_delay_samples(input_wav: str | Path, output_wav: str | Path, delay_ms: float = 25.0) -> Path:
    """Shift audio earlier by delay_ms (e.g. afftdn 25 ms / 1200 samples @ 48 kHz) to maintain A/V sync."""
    sr, samples = _read_pcm16_mono(input_wav)
    shift = int(round(sr * (delay_ms / 1000.0)))
    if shift <= 0 or shift >= len(samples):
        return _write_pcm16_mono(output_wav, sr, samples)
    shifted = samples[shift:] + [0] * shift
    return _write_pcm16_mono(output_wav, sr, shifted)


def estimate_audio_delay_ms(ref_wav: str | Path, proc_wav: str | Path, max_lag_ms: float = 80.0) -> float:
    """Estimate lag (ms) between processed and reference WAVs via 1 ms envelope cross-correlation."""
    sr_r, ref = _read_pcm16_mono(ref_wav)
    sr_p, proc = _read_pcm16_mono(proc_wav)
    step = max(1, int(sr_r * 0.001))  # 1 ms bins
    n_bins = min(len(ref), len(proc), sr_r * 15) // step
    if n_bins < 20:
        return 0.0

    env_r = [sum(abs(x) for x in ref[i * step : (i + 1) * step]) / step for i in range(n_bins)]
    env_p = [sum(abs(x) for x in proc[i * step : (i + 1) * step]) / step for i in range(n_bins)]
    max_lag = int(max_lag_ms)

    best_lag = 0
    best_corr = -1.0
    for lag in range(-max_lag, max_lag + 1):
        s = 0.0
        for i in range(max_lag, n_bins - max_lag):
            s += env_r[i] * env_p[i + lag]
        if s > best_corr:
            best_corr = s
            best_lag = lag
    return float(best_lag)


def measure_loudness_ffmpeg(media_path: str | Path) -> dict[str, float]:
    """Measure integrated LUFS and true peak using FFmpeg loudnorm JSON output."""
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(media_path),
        "-af",
        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    stderr = res.stderr
    start_idx = stderr.rfind("{")
    end_idx = stderr.rfind("}")
    if start_idx == -1 or end_idx <= start_idx:
        raise RuntimeError(f"Could not parse loudnorm JSON from FFmpeg stderr: {stderr[-300:]}")
    data = json.loads(stderr[start_idx : end_idx + 1])
    return {
        "input_i": float(data["input_i"]),
        "input_tp": float(data["input_tp"]),
        "input_lra": float(data["input_lra"]),
        "input_thresh": float(data["input_thresh"]),
    }
