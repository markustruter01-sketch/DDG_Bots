"""OpusClip Pro policy guard, transcript-to-raw mapper, 10 ms silence re-snapper, and free local fallback."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .audio_engine import find_nearest_silence_boundary
from .models import OpusClipCandidate, Transcript


class PolicyViolationError(PermissionError):
    """Raised when an operation breaks DDG's OpusClip usage/publish guardrails."""


class OpusClipPolicyGuard:
    """Enforces Markus's 23 Nov 2026 OpusClip Pro rules (info@digitaldynamics-group.com)."""

    def __init__(
        self,
        credits_remaining: int = 261,
        warn_over_credits: int = 140,
        credits_per_source_min: int = 1,
    ) -> None:
        self.credits_remaining = credits_remaining
        self.warn_over_credits = warn_over_credits
        self.credits_per_source_min = credits_per_source_min

    def check_credit_budget(self, source_duration_min: float) -> dict[str, Any]:
        """Check opusclip_get_usage policy BEFORE submit; require explicit yes if cost > ~140."""
        cost = max(1, int(round(source_duration_min * self.credits_per_source_min)))
        remaining_after = self.credits_remaining - cost
        over_warn = cost > self.warn_over_credits
        insufficient = cost > self.credits_remaining
        requires_approval = over_warn or insufficient

        if insufficient:
            msg = (
                f"BLOCKED: source needs ~{cost} OpusClip credits, only {self.credits_remaining} remaining. "
                "Use local_hook_scorer (A$0) instead."
            )
        elif over_warn:
            msg = (
                f"APPROVAL REQUIRED: OpusClip submit costs ~{cost} credits (> {self.warn_over_credits} threshold), "
                f"leaving {remaining_after} of {self.credits_remaining}. Ask Markus before submitting."
            )
        else:
            msg = (
                f"OK: OpusClip submit costs ~{cost} credits, leaving {remaining_after} of {self.credits_remaining}."
            )

        return {
            "cost_credits": cost,
            "credits_remaining_before": self.credits_remaining,
            "credits_remaining_after": remaining_after,
            "exceeds_warn_threshold": over_warn,
            "insufficient_credits": insufficient,
            "requires_markus_approval": requires_approval,
            "message": msg,
        }

    @staticmethod
    def validate_submission(
        *,
        is_raw_source: bool,
        is_private: bool,
        analysis_only: bool,
    ) -> None:
        if not is_raw_source:
            raise PolicyViolationError("OpusClip must ONLY receive the raw source so timestamps map to raw.")
        if not is_private:
            raise PolicyViolationError("OpusClip project MUST be marked private.")
        if not analysis_only:
            raise PolicyViolationError("OpusClip must be analysis-only; our pipeline renders everything that ships.")

    @staticmethod
    def block_raw_publish() -> None:
        raise PolicyViolationError(
            "HARD BLOCK: Never publish, schedule, or share OpusClip raw output (no blur, no censor, no Night Glass)."
        )


def _norm_tokens(text: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split() if t]


def map_clip_transcript_to_raw(
    clip_text: str,
    project_transcript: Transcript,
    rms_series: list[tuple[float, float]] | None = None,
    pad_ms: int = 120,
    noise_floor_db: float = -42.0,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Map an OpusClip transcript onto raw project timestamps and re-snap to 10 ms silence (G10)."""
    clip_toks = _norm_tokens(clip_text)
    if not clip_toks or not project_transcript.words:
        return None, None, None, None

    words = sorted(project_transcript.words, key=lambda w: w.start)
    proj_toks = [_norm_tokens(w.word)[0] if _norm_tokens(w.word) else "" for w in words]

    win_len = len(clip_toks)
    best_score = 0.0
    best_span: tuple[int, int] | None = None

    # Allow slight length variation in ASR wording (+/- 20%)
    min_w = max(1, int(win_len * 0.8))
    max_w = min(len(proj_toks), max(win_len + 2, int(win_len * 1.25)))

    for start_idx in range(0, max(1, len(proj_toks) - min_w + 1)):
        for span_len in (win_len, min_w, min(max_w, len(proj_toks) - start_idx)):
            end_idx = min(len(proj_toks), start_idx + span_len)
            cand = proj_toks[start_idx:end_idx]
            if not cand:
                continue
            score = SequenceMatcher(None, clip_toks, cand).ratio()
            if score > best_score:
                best_score = score
                best_span = (start_idx, end_idx - 1)

    if best_span is None or best_score < 0.45:
        return None, None, None, None

    raw_start = words[best_span[0]].start
    raw_end = words[best_span[1]].end

    if rms_series:
        pad_s = max(0.10, min(0.15, pad_ms / 1000.0))
        s_snap, s_db = find_nearest_silence_boundary(
            rms_series,
            max(0.0, raw_start - pad_s),
            search_window_s=0.6,
            pad_ms=pad_ms,
            noise_floor_db=noise_floor_db,
        )
        e_snap, e_db = find_nearest_silence_boundary(
            rms_series,
            raw_end + pad_s,
            search_window_s=0.6,
            pad_ms=pad_ms,
            noise_floor_db=noise_floor_db,
        )
        return s_snap, e_snap, s_db, e_db

    return round(raw_start, 3), round(raw_end, 3), None, None


def map_opusclip_candidates(
    candidates: list[OpusClipCandidate],
    project_transcript: Transcript,
    rms_series: list[tuple[float, float]] | None = None,
    pad_ms: int = 120,
    noise_floor_db: float = -42.0,
) -> list[OpusClipCandidate]:
    """Map all OpusClip candidates to raw times and re-place cuts in 10 ms measured silence."""
    mapped: list[OpusClipCandidate] = []
    for c in candidates:
        s, e, s_db, e_db = map_clip_transcript_to_raw(
            c.transcript_text,
            project_transcript,
            rms_series=rms_series,
            pad_ms=pad_ms,
            noise_floor_db=noise_floor_db,
        )
        mapped.append(
            OpusClipCandidate(
                clip_id=c.clip_id,
                title=c.title,
                transcript_text=c.transcript_text,
                virality_score=c.virality_score,
                mapped_start_s=s,
                mapped_end_s=e,
                start_rms_db=s_db,
                end_rms_db=e_db,
                approved=c.approved,
                raw_source_only=True,
            )
        )
    return mapped


def local_hook_scorer(
    transcript: Transcript,
    rms_series: list[tuple[float, float]] | None = None,
    max_clips: int = 5,
) -> list[OpusClipCandidate]:
    """A$0/token offline Shorts hook discovery fallback when OpusClip credits are conserved."""
    words = sorted(transcript.words, key=lambda w: w.start)
    if not words:
        return []

    # Group into complete sentence-bounded chunks (~15-35 s)
    chunks: list[list[Any]] = []
    cur: list[Any] = []
    for w in words:
        cur.append(w)
        dur = w.end - cur[0].start
        ends_sentence = w.word.strip().endswith((".", "!", "?"))
        if ends_sentence and dur >= 15.0:
            chunks.append(cur)
            cur = []
        elif dur >= 35.0 and ends_sentence:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    hook_keywords = {
        "zero", "free", "cost", "ai", "bot", "coffee", "money", "trading", "broken",
        "insane", "edit", "crashed", "million", "secret", "mistake", "built",
    }
    scored: list[OpusClipCandidate] = []
    for idx, ch in enumerate(chunks, start=1):
        text = " ".join(w.word for w in ch)
        toks = set(_norm_tokens(text))
        kw_hits = len(toks & hook_keywords)
        score = min(98.0, 62.0 + kw_hits * 7.5 + (6.0 if "!" in text or "?" in text else 0.0))
        start_s = ch[0].start
        end_s = ch[-1].end
        s_db = e_db = None
        if rms_series:
            start_s, s_db = find_nearest_silence_boundary(rms_series, max(0.0, start_s - 0.12))
            end_s, e_db = find_nearest_silence_boundary(rms_series, end_s + 0.12)
        scored.append(
            OpusClipCandidate(
                clip_id=f"local_hook_{idx:02d}",
                title=f"Local Hook #{idx}",
                transcript_text=text,
                virality_score=round(score, 1),
                mapped_start_s=start_s,
                mapped_end_s=end_s,
                start_rms_db=s_db,
                end_rms_db=e_db,
                approved=False,  # Always wait for Markus's pick before rendering
                raw_source_only=True,
            )
        )

    scored.sort(key=lambda c: c.virality_score, reverse=True)
    return scored[:max_clips]
