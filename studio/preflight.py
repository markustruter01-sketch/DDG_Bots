"""Unified G0-G11 Preflight Verification Runner writing PREFLIGHT_FINAL.md and preflight_report.json."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .audio_engine import audit_g5b_no_privacy_mutes, is_allowed_swear_word, rms_at_time
from .blur_engine import audit_g8b_blur_stability
from .layout_grid import (
    GRID_HEIGHT,
    GRID_WIDTH,
    align_check,
    duration_and_wild_cap_check,
    face_clearance_check,
    overlap_and_area_check,
)
from .media_probe import check_master_bitrate, check_source_quality
from .mentions import audit_g11_mentions
from .models import (
    EditPlan,
    GateResult,
    PreflightReport,
    Transcript,
    load_rules,
    now_aest_iso,
    save_json,
)
from .night_glass_gfx import contains_emoji
from .transcribe import audit_transcript_holes


def _check_g0_numbers(plan: EditPlan, numbers_check_log_path: str | Path | None = None) -> GateResult:
    if plan.hud is None:
        return GateResult(
            gate_id="G0_NUMBERS",
            name="HUD & Number Source Verification (G0)",
            passed=True,
            summary="No HUD configured on this plan (Shorts/clip mode).",
        )
    balanced, msg = plan.hud.is_balanced()
    issues: list[str] = []
    if not balanced:
        issues.append(msg)
    if numbers_check_log_path is not None and not Path(numbers_check_log_path).exists():
        issues.append(f"Missing numbers_check.md log at {numbers_check_log_path}.")
    return GateResult(
        gate_id="G0_NUMBERS",
        name="HUD & Number Source Verification (G0)",
        passed=len(issues) == 0,
        summary=msg if not issues else "; ".join(issues),
        details=issues,
    )


def _check_g6_avatar_and_zoom(plan: EditPlan) -> GateResult:
    issues: list[str] = []
    av = plan.avatar
    if av.enabled:
        if av.flipped:
            issues.append("G6 FAIL: Marketing/Freya avatar must NEVER be horizontally flipped.")
        if not av.faces_left:
            issues.append("G6 FAIL: Avatar must always face left/toward center content.")
        if not av.composite_above_all_blurs:
            issues.append("G6 FAIL: Avatar MUST be composited ABOVE all blur layers.")

    for z in plan.zooms:
        if z.is_dramatic:
            push_dur = z.peak_s - z.start_s
            if not (3.0 <= push_dur <= 5.0):
                issues.append(
                    f"Zoom '{z.id}' dramatic push-in duration {push_dur:.2f}s must be 3.0-5.0s."
                )
            if z.anchor != [0, 1080]:
                issues.append(
                    f"Zoom '{z.id}' anchor {z.anchor} must be bottom-left [0, 1080] (webcam focal point)."
                )

    return GateResult(
        gate_id="G6_AVATAR_ZOOM",
        name="Avatar Layering & Bottom-Left Dramatic Zooms (G6)",
        passed=len(issues) == 0,
        summary=(
            "Avatar orientation/layering and dramatic zoom anchors verified."
            if not issues
            else f"{len(issues)} G6 avatar/zoom issue(s)."
        ),
        details=issues,
    )


def _check_g7_webcam_windows(plan: EditPlan) -> GateResult:
    if not plan.window_masks:
        return GateResult(
            gate_id="G7_WEBCAM_WINDOWS",
            name="Webcam Per-Pane Window Masks (G7)",
            passed=True,
            summary="No webcam window masks attached (or skipped).",
        )
    issues: list[str] = []
    behind_head_excluded = any(w.exclude_behind_head for w in plan.window_masks)
    if not behind_head_excluded:
        issues.append("Window directly behind Markus's head must have exclude_behind_head=True.")
    for w in plan.window_masks:
        if len(w.polygon_norm) < 3:
            issues.append(f"Window mask '{w.id}' polygon has < 3 vertices.")
    return GateResult(
        gate_id="G7_WEBCAM_WINDOWS",
        name="Webcam Per-Pane Window Masks (G7)",
        passed=len(issues) == 0,
        summary=(
            f"{len(plan.window_masks)} static webcam-local window pane(s) verified (behind-head clear)."
            if not issues
            else "; ".join(issues)
        ),
        details=issues,
    )


def _check_g9_brand_and_ai_disclosure(plan: EditPlan) -> GateResult:
    issues: list[str] = []
    if plan.youtube_synthetic_flag:
        issues.append("G9 FAIL: youtube_synthetic_flag must be False for real Markus footage (31 Oct rule).")
    if "Made with AI tools." not in (plan.description_ai_line or ""):
        issues.append("G9 FAIL: Description must include 'Made with AI tools.'.")
    if plan.mode != "short" and plan.tv_icon_enabled:
        issues.append("G9/G2 FAIL: tv_icon_enabled must be False for episodes (24 Nov rule: static audio only).")
    for o in plan.overlays:
        if contains_emoji(o.title):
            issues.append(f"G9 FAIL: Overlay '{o.id}' title contains forbidden emoji.")
        if o.extra.get("uses_glitch_style") and not o.extra.get("is_official_intro_outro"):
            issues.append(f"G9 FAIL: Glitch effect forbidden on new Night Glass overlay '{o.id}'.")
    return GateResult(
        gate_id="G9_BRAND_DISCLOSURE",
        name="Night Glass v5 Brand & YouTube AI Policy (G9)",
        passed=len(issues) == 0,
        summary=(
            "Night Glass compliance, zero emojis, and YouTube AI disclosure policy verified."
            if not issues
            else f"{len(issues)} brand/disclosure violation(s)."
        ),
        details=issues,
    )


def _check_g10_cuts(
    plan: EditPlan,
    rms_series: list[tuple[float, float]] | None = None,
    noise_floor_db: float = -42.0,
) -> GateResult:
    issues: list[str] = []
    for c in plan.cuts:
        if not c.approved:
            continue
        if c.is_short_pause or c.duration < 4.0:
            issues.append(
                f"Cut '{c.id}' ({c.duration:.2f}s) is a short dead-air cut — strictly forbidden (23 Nov rule)."
            )
        if rms_series:
            s_db = rms_at_time(rms_series, c.start_s)
            e_db = rms_at_time(rms_series, c.end_s)
            if s_db > noise_floor_db:
                issues.append(f"Cut '{c.id}' start {c.start_s:.2f}s RMS {s_db:.1f} dBFS > {noise_floor_db} dBFS.")
            if e_db > noise_floor_db:
                issues.append(f"Cut '{c.id}' end {c.end_s:.2f}s RMS {e_db:.1f} dBFS > {noise_floor_db} dBFS.")
        elif (c.start_rms_db is not None and c.start_rms_db > noise_floor_db) or (
            c.end_rms_db is not None and c.end_rms_db > noise_floor_db
        ):
            issues.append(f"Cut '{c.id}' recorded boundary RMS exceeds {noise_floor_db} dBFS.")

    return GateResult(
        gate_id="G10_CUTS",
        name="10 ms Silence Cut Snapping & No Dead-Air Cuts (G10)",
        passed=len(issues) == 0,
        summary=(
            f"Verified {sum(1 for c in plan.cuts if c.approved)} approved cut(s) safely in 10 ms silence."
            if not issues
            else f"{len(issues)} G10 cut boundary violation(s)."
        ),
        details=issues,
    )


def run_preflight(
    plan: EditPlan,
    *,
    source_probe: dict[str, Any] | None = None,
    master_probe: dict[str, Any] | None = None,
    transcript: Transcript | None = None,
    rms_series: list[tuple[float, float]] | None = None,
    raw_wav: str | Path | None = None,
    proc_wav: str | Path | None = None,
    loudness: dict[str, float] | None = None,
    residual_sync_ms: float | None = None,
    ocr_texts_after_blur: list[str] | None = None,
    frame_blur_presence: dict[str, list[bool]] | None = None,
    numbers_check_log_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    allowed_roots: list[str | Path] | None = None,
    rules: dict[str, Any] | None = None,
) -> PreflightReport:
    """Execute complete G0-G11 preflight verification and optionally write PREFLIGHT_FINAL.md."""
    if rules is None:
        rules = load_rules()

    gates: list[GateResult] = []
    gates.append(_check_g0_numbers(plan, numbers_check_log_path=numbers_check_log_path))

    # G1 Source & Master Bitrate
    if source_probe is not None:
        g1 = check_source_quality(
            source_probe,
            min_width=rules["G1_source_and_master"]["min_width"],
            min_height=rules["G1_source_and_master"]["min_height"],
            min_fps=rules["G1_source_and_master"]["min_fps"],
        )
        if master_probe is not None:
            ok_br, br_msg = check_master_bitrate(
                master_probe,
                min_bps=rules["G1_source_and_master"]["master_bitrate_bps_min"],
                max_bps=rules["G1_source_and_master"]["master_bitrate_bps_max"],
            )
            if not ok_br:
                g1.passed = False
                g1.details.append(br_msg)
                g1.summary = br_msg
        gates.append(g1)

    # G2 Audio Loudness & Sync
    if loudness is not None or residual_sync_ms is not None:
        g2_issues: list[str] = []
        if loudness is not None:
            if abs(loudness["input_i"] - (-14.0)) > rules["G2_G5b_audio"]["lufs_tolerance"]:
                g2_issues.append(f"Integrated loudness {loudness['input_i']:.1f} LUFS outside -14 +/- 1.5 LUFS.")
            if loudness["input_tp"] >= rules["G2_G5b_audio"]["true_peak_max_db"]:
                g2_issues.append(f"True peak {loudness['input_tp']:.2f} dBTP >= -1.5 dBTP.")
        if residual_sync_ms is not None and abs(residual_sync_ms) > rules["G2_G5b_audio"]["max_residual_sync_ms"]:
            g2_issues.append(f"Residual audio sync lag {residual_sync_ms:.1f} ms > 5.0 ms.")
        gates.append(
            GateResult(
                gate_id="G2_AUDIO_SYNC",
                name="Audio Loudness (-14 LUFS) & Sync (G2)",
                passed=len(g2_issues) == 0,
                summary="Audio loudness & sync within broadcast tolerance." if not g2_issues else "; ".join(g2_issues),
                details=g2_issues,
            )
        )

    # G3 Transcript / ASR Holes
    if transcript is not None:
        gates.append(audit_transcript_holes(transcript, rms_series=rms_series))

    # G4 Grid & Alignment
    if plan.mode != "short":
        gates.append(align_check(plan.overlays, tol_px=rules["G4_grid_and_text"]["grid_tolerance_px"]))

    # G5 Overlays (Face clearance, Overlap, 75% Area Cap, Durations & Wild Cap)
    frame_w = 1080 if plan.mode == "short" else GRID_WIDTH
    frame_h = 1920 if plan.mode == "short" else GRID_HEIGHT
    g5_issues: list[str] = []
    g5_issues.extend(
        face_clearance_check(
            plan.overlays,
            plan.face_box,
            min_margin_ratio=rules["G5_overlays"]["min_face_clearance_ratio"],
            frame_w=frame_w,
            frame_h=frame_h,
        )
    )
    ov_issues, peak_area = overlap_and_area_check(
        plan.overlays,
        area_cap=rules["G5_overlays"]["max_combined_area_ratio"],
        frame_w=frame_w,
        frame_h=frame_h,
    )
    g5_issues.extend(ov_issues)
    g5_issues.extend(
        duration_and_wild_cap_check(
            plan.overlays,
            mode=plan.mode,
            max_wild_ratio=rules["G5_overlays"]["max_wild_ratio"],
        )
    )
    gates.append(
        GateResult(
            gate_id="G5_OVERLAYS",
            name="Overlays Area Cap (<=75%), Clearance & Timing (G5)",
            passed=len(g5_issues) == 0,
            summary=(
                f"All overlays verified (peak combined footprint {peak_area*100:.1f}%)."
                if not g5_issues
                else f"{len(g5_issues)} overlay violation(s)."
            ),
            details=g5_issues,
        )
    )

    # G5b Swear-only static & zero privacy mutes
    swear_scope_issues: list[str] = []
    for sp in plan.swear_spans:
        if not is_allowed_swear_word(str(sp.get("word", ""))):
            swear_scope_issues.append(
                f"Illegal censor target '{sp.get('word')}' — ONLY fuck/shit forms may be censored."
            )
    if raw_wav and proc_wav and transcript is not None:
        g5b = audit_g5b_no_privacy_mutes(raw_wav, proc_wav, transcript, plan.swear_spans)
        if swear_scope_issues:
            g5b.passed = False
            g5b.details.extend(swear_scope_issues)
        gates.append(g5b)
    elif swear_scope_issues or plan.swear_spans:
        gates.append(
            GateResult(
                gate_id="G5b_AUDIO_CENSOR",
                name="Swear-Only Static Whitelist (G5b)",
                passed=len(swear_scope_issues) == 0,
                summary="Swear whitelist verified (fuck/shit forms only)." if not swear_scope_issues else "; ".join(swear_scope_issues),
                details=swear_scope_issues,
            )
        )

    gates.append(_check_g6_avatar_and_zoom(plan))
    gates.append(_check_g7_webcam_windows(plan))
    gates.append(
        audit_g8b_blur_stability(
            plan.blur_spans,
            webcam_rect=plan.webcam_rect,
            min_sigma=rules["G8_G8b_blurs_and_ocr"]["blur_sigma_min"],
            min_downscale=rules["G8_G8b_blurs_and_ocr"]["downscale_factor"],
            ocr_texts_after_blur=ocr_texts_after_blur,
            sensitive_terms=rules["G8_G8b_blurs_and_ocr"]["sensitive_terms"],
            sensitive_regexes=rules["G8_G8b_blurs_and_ocr"]["sensitive_ocr_regexes"],
            frame_blur_presence=frame_blur_presence,
        )
    )
    gates.append(_check_g9_brand_and_ai_disclosure(plan))
    gates.append(_check_g10_cuts(plan, rms_series=rms_series, noise_floor_db=rules["G10_cuts"]["noise_floor_db"]))
    gates.append(audit_g11_mentions(plan, min_duration_s=rules["G11_mentions"]["min_duration_s"]))

    all_passed = all(g.passed for g in gates if g.blocking)
    report = PreflightReport(
        job_id=plan.job_id,
        checked_at_aest=now_aest_iso(),
        passed=all_passed,
        gates=gates,
    )

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        save_json(out_dir / "preflight_report.json", report.to_dict(), allowed_roots=allowed_roots)
        md_lines = [
            f"# Preflight Report: {plan.job_id}",
            f"- Checked (AEST): `{report.checked_at_aest}`",
            f"- Overall Status: **{'PASS' if report.passed else 'FAIL'}**",
            "",
            "| Gate | Name | Status | Summary |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for g in gates:
            status = "PASS" if g.passed else "FAIL"
            md_lines.append(f"| `{g.gate_id}` | {g.name} | **{status}** | {g.summary} |")
        md_lines.append("")
        for g in gates:
            if g.details:
                md_lines.append(f"## {g.gate_id} Details")
                for d in g.details:
                    md_lines.append(f"- {d}")
                md_lines.append("")
        (out_dir / "PREFLIGHT_FINAL.md").write_text("\n".join(md_lines), encoding="utf-8")

    return report
