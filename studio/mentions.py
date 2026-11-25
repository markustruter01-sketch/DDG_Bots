"""Transcript brand/product mentions scanner and G11 preflight gate."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import EditPlan, GateResult, MentionItem, Transcript, load_rules, save_json


def _normalize_phrase(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]+", " ", text.lower()).strip()


def scan_mentions(
    transcript: Transcript,
    rules: dict[str, Any] | None = None,
) -> list[MentionItem]:
    """Scan full transcript for product, service, company, or app mentions with ASR alias mapping."""
    if rules is None:
        rules = load_rules()

    aliases: dict[str, dict[str, Any]] = rules.get("G11_mentions", {}).get("asr_brand_aliases", {})
    sorted_keys = sorted(aliases.keys(), key=lambda k: len(k.split()), reverse=True)

    words = sorted(transcript.words, key=lambda w: w.start)
    norm_tokens = [_normalize_phrase(w.word) for w in words]

    found: dict[str, MentionItem] = {}
    i = 0
    while i < len(words):
        matched_key = None
        matched_len = 0
        for key in sorted_keys:
            k_parts = key.lower().split()
            n = len(k_parts)
            if i + n <= len(norm_tokens) and norm_tokens[i : i + n] == k_parts:
                matched_key = key
                matched_len = n
                break
        if matched_key is not None:
            meta = aliases[matched_key]
            official = meta["official_name"]
            ts = round(words[i].start, 3)
            if official not in found:
                found[official] = MentionItem(
                    raw_token=" ".join(w.word for w in words[i : i + matched_len]),
                    official_name=official,
                    url=meta.get("url", ""),
                    category=meta.get("category", "product"),
                    is_private_business=bool(meta.get("is_private_business", False)),
                    timestamps=[ts],
                    on_screen=False,
                    visual_asset=meta.get("asset_hint", ""),
                )
            else:
                found[official].timestamps.append(ts)
            i += matched_len
        else:
            i += 1

    return list(found.values())


def save_mentions_checklist(
    mentions: list[MentionItem],
    output_path: str | Path,
    allowed_roots: list[str | Path] | None = None,
) -> Path:
    return save_json(
        output_path,
        {"mentions": [m.to_dict() for m in mentions]},
        allowed_roots=allowed_roots,
    )


def attach_mention_overlays_info(plan: EditPlan) -> None:
    """Sync MentionItem.on_screen flags against actual planned overlays in EditPlan."""
    for mention in plan.mentions:
        if mention.overlay_id:
            matching = [o for o in plan.overlays if o.id == mention.overlay_id]
            if matching:
                mention.on_screen = True
                continue
        # Fallback match by title/official_name substring inside non-persistent overlays
        name_low = mention.official_name.lower()
        for ov in plan.overlays:
            if ov.kind in ("mention_card", "deep_graphic", "heavy_card", "quick_chip") and (
                name_low in ov.title.lower()
                or mention.raw_token.lower() in ov.title.lower()
                or ov.extra.get("official_name", "").lower() == name_low
            ):
                mention.on_screen = True
                mention.overlay_id = ov.id
                break


def audit_g11_mentions(
    plan: EditPlan,
    min_duration_s: float = 4.5,
) -> GateResult:
    """G11: Fail if any non-skipped product/service/company mention has no >=4.5 s on-screen visual."""
    attach_mention_overlays_info(plan)
    issues: list[str] = []
    ov_by_id = {o.id: o for o in plan.overlays}

    for m in plan.mentions:
        if m.skipped_by_markus:
            continue
        if m.is_private_business:
            # Private businesses stay blurred/hidden unless Markus explicitly turns on_screen on
            continue
        if not m.on_screen:
            issues.append(
                f"Mention '{m.official_name}' (heard at {m.timestamps}) has no planned on-screen visual."
            )
            continue
        ov = ov_by_id.get(m.overlay_id)
        if ov is None:
            issues.append(
                f"Mention '{m.official_name}' references missing overlay_id '{m.overlay_id}'."
            )
        elif plan.mode != "short" and ov.duration < min_duration_s:
            issues.append(
                f"Mention '{m.official_name}' overlay '{ov.id}' duration {ov.duration:.2f}s < {min_duration_s:.1f}s."
            )

    return GateResult(
        gate_id="G11_MENTIONS",
        name="Every Mentioned Product/Company Shown On Screen (G11)",
        passed=len(issues) == 0,
        summary=(
            f"All {len(plan.mentions)} mention(s) resolved and scheduled on screen."
            if not issues
            else f"{len(issues)} unvisualized or under-duration mention(s)."
        ),
        details=issues,
    )
