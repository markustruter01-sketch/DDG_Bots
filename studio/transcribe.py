"""Local WhisperX transcription adapter + G3 ASR hole & drift detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import GateResult, Transcript, WordTimestamp, load_json, save_json
from .vram_baton import VramBaton


def load_transcript_json(path: str | Path) -> Transcript:
    return Transcript.from_dict(load_json(path))


def save_transcript_json(transcript: Transcript, path: str | Path, allowed_roots: list[str | Path] | None = None) -> Path:
    return save_json(path, transcript.to_dict(), allowed_roots=allowed_roots)


def transcribe_video(
    audio_or_video_path: str | Path,
    output_json: str | Path,
    model_name: str = "large-v3-turbo",
    compute_type: str = "int8_float16",
    batch_size: int = 8,
    device: str = "cuda",
    allowed_roots: list[str | Path] | None = None,
) -> Transcript:
    """Transcribe locally with WhisperX word-level phoneme alignment inside VramBaton."""
    try:
        import whisperx  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "whisperx is not installed in this environment. Run scripts/setup_local_env.ps1 "
            "or pass an existing word-timed transcript JSON."
        ) from exc

    with VramBaton("whisperx_transcribe"):
        audio = whisperx.load_audio(str(audio_or_video_path))
        model = whisperx.load_model(model_name, device, compute_type=compute_type)
        result = model.transcribe(audio, batch_size=batch_size)
        lang = result.get("language", "en")
        align_model, metadata = whisperx.load_align_model(language_code=lang, device=device)
        aligned = whisperx.align(
            result["segments"], align_model, metadata, audio, device, return_char_alignments=False
        )
        del model
        del align_model

    words: list[WordTimestamp] = []
    for seg in aligned.get("segments", []):
        speaker = seg.get("speaker", "Markus")
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            words.append(
                WordTimestamp(
                    word=str(w["word"]).strip(),
                    start=float(w["start"]),
                    end=float(w["end"]),
                    confidence=float(w.get("score", 1.0)),
                    speaker=speaker,
                )
            )

    transcript = Transcript(
        source_path=str(audio_or_video_path),
        language=lang,
        words=words,
        segments=list(aligned.get("segments", [])),
    )
    save_transcript_json(transcript, output_json, allowed_roots=allowed_roots)
    return transcript


def audit_transcript_holes(
    transcript: Transcript,
    rms_series: list[tuple[float, float]] | None = None,
    max_word_duration_s: float = 1.5,
    max_speech_gap_s: float = 3.0,
    speech_energy_threshold_db: float = -35.0,
) -> GateResult:
    """Detect stretched words (>1.5 s) and speech-energy-without-words holes (G3)."""
    issues: list[str] = []
    long_words: list[str] = []

    for w in transcript.words:
        if w.duration > max_word_duration_s:
            long_words.append(f"Stretched word '{w.word}' ({w.duration:.2f}s at {w.start:.2f}s)")

    if long_words:
        issues.extend(long_words)

    if rms_series and transcript.words:
        words = sorted(transcript.words, key=lambda x: x.start)
        for prev_w, next_w in zip(words, words[1:]):
            gap = next_w.start - prev_w.end
            if gap <= max_speech_gap_s:
                continue
            start_bin = max(0, int((prev_w.end + 0.1) / 0.010))
            end_bin = min(len(rms_series), int((next_w.start - 0.1) / 0.010))
            if end_bin <= start_bin:
                continue
            active_bins = sum(1 for k in range(start_bin, end_bin) if rms_series[k][1] > speech_energy_threshold_db)
            active_s = active_bins * 0.010
            if active_s >= 1.5:
                issues.append(
                    f"ASR dropout hole {prev_w.end:.2f}s-{next_w.start:.2f}s: "
                    f"{active_s:.2f}s of active speech energy with 0 transcribed words (re-run without VAD)."
                )

    if not transcript.words:
        issues.append("Transcript has 0 word timestamps.")

    return GateResult(
        gate_id="G3_SUBTITLES_ASR",
        name="Transcript & Subtitle Coverage (G3)",
        passed=len(issues) == 0,
        summary=(
            f"{len(transcript.words)} words verified with 0 ASR holes or stretched words."
            if not issues
            else f"{len(issues)} transcript coverage issue(s) found."
        ),
        details=issues,
    )
