"""End-to-end DDG Local Bot Studio pipeline orchestrator & folder watcher."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from .ai_director import OllamaClient, generate_social_copy
from .audio_engine import (
    apply_swear_static_censor,
    detect_swears,
    extract_wav_mono,
    measure_rms_10ms,
    propose_long_gaps,
)
from .blur_engine import build_webcam_window_mask_png, stabilize_blur_spans
from .calibration import log_job_time, predict_minutes
from .layout_grid import snap_rect_to_grid
from .media_probe import probe_media, sha256_file
from .mentions import save_mentions_checklist, scan_mentions
from .models import (
    AvatarPlacement,
    EditPlan,
    HudNumbers,
    OverlayItem,
    Rect,
    STUDIO_ROOT,
    Transcript,
    WebcamRect,
    WindowPaneMask,
    assert_in_allowed_roots,
    load_json,
    load_rules,
    load_settings,
    now_aest_iso,
    save_json,
)
from .night_glass_gfx import (
    generate_ass_subtitles,
    render_business_tab_bar,
    render_glass_panel,
    render_hud_bar,
)
from .opusclip_bridge import local_hook_scorer
from .preflight import run_preflight
from .render_engine import render_vertical_short, render_video_from_plan, render_windows_and_concat
from .transcribe import load_transcript_json, transcribe_video
from .vram_baton import is_gpu_busy_for_user


VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm"}


def run_job(
    source_video: str | Path,
    *,
    job_id: str | None = None,
    mode: str = "preview",
    transcript_json: str | Path | None = None,
    hud_json: str | Path | None = None,
    raw_blur_detections: list[dict[str, Any]] | None = None,
    offline: bool = True,
    studio_root: str | Path = STUDIO_ROOT,
    footage_root: str | Path | None = None,
) -> dict[str, Any]:
    """Process a raw video through ingest -> audio/censor -> mentions -> Night Glass -> preflight -> render."""
    t_start = time.monotonic()
    settings = load_settings(studio_root)
    rules = load_rules(studio_root)
    f_root = Path(footage_root or settings["footage_root"])
    allowed_roots = [Path(studio_root).resolve(), f_root.resolve()]

    src_path = Path(source_video).resolve()
    assert_in_allowed_roots(src_path, allowed_roots)

    jid = job_id or f"{src_path.stem}_{int(time.time())}"
    proc_dir = assert_in_allowed_roots(f_root / settings["footage_subdirs"]["processing"] / jid, allowed_roots)
    rev_dir = assert_in_allowed_roots(f_root / settings["footage_subdirs"]["review"] / jid, allowed_roots)
    proc_dir.mkdir(parents=True, exist_ok=True)
    rev_dir.mkdir(parents=True, exist_ok=True)

    probe = probe_media(src_path)
    dur_s = float(probe.get("duration_s", 0.0))

    raw_wav = proc_dir / "raw_audio.wav"
    proc_wav = proc_dir / "clean_audio.wav"
    extract_wav_mono(src_path, raw_wav)
    rms_series = measure_rms_10ms(raw_wav)

    if transcript_json and Path(transcript_json).exists():
        transcript = load_transcript_json(transcript_json)
    elif not offline:
        transcript = transcribe_video(
            src_path,
            proc_dir / "transcript.json",
            model_name=settings["whisper"]["model"],
            compute_type=settings["whisper"]["compute_type"],
            batch_size=settings["whisper"]["batch_size"],
            device=settings["whisper"]["device"],
            allowed_roots=allowed_roots,
        )
    else:
        transcript = Transcript(source_path=str(src_path), words=[], segments=[])

    swear_spans = detect_swears(transcript)
    apply_swear_static_censor(
        raw_wav,
        proc_wav,
        swear_spans,
        gain=rules["G2_G5b_audio"]["censor_gain"],
        fade_ms=rules["G2_G5b_audio"]["censor_fade_ms"],
        band_hz=tuple(rules["G2_G5b_audio"]["censor_noise_band_hz"]),
    )

    mentions = scan_mentions(transcript, rules=rules)
    save_mentions_checklist(mentions, proc_dir / "mentions_checklist.json", allowed_roots=allowed_roots)
    gap_proposals = propose_long_gaps(transcript, rms_series)
    hook_candidates = local_hook_scorer(transcript, rms_series=rms_series)

    # HUD from Control JSON or unknown placeholders ("—")
    if hud_json and Path(hud_json).exists():
        hud = HudNumbers.from_dict(load_json(hud_json))
    else:
        hud = HudNumbers(
            followers=None, views=None, likes=None,
            expenses=None, gross_revenue=None, debt=None,
            charity_deducted=None, net_profit=None,
            source_label="DDG Control",
            checked_at_aest=now_aest_iso(),
        )

    numbers_log = proc_dir / "numbers_check.md"
    numbers_log.write_text(
        f"# Numbers Check ({now_aest_iso()})\n- Source: {hud.source_label}\n- HUD: `{hud.to_dict()}`\n",
        encoding="utf-8",
    )

    # Generate Night Glass HUD, Tab Bar, and Mention visual cards
    overlay_images: dict[str, str] = {}
    overlays: list[OverlayItem] = []

    hud_png = proc_dir / "hud_bar.png"
    render_hud_bar(hud, hud_png, width=1340, height=72)
    overlay_images["hud_bar"] = str(hud_png)
    overlays.append(
        OverlayItem(
            id="hud_bar", kind="hud", title="DDG Control HUD",
            start_s=0.0, end_s=max(dur_s, 1.0),
            x=20, y=20, width=1340, height=72, is_persistent=True, asset_path=str(hud_png),
        )
    )

    tab_png = proc_dir / "tab_bar.png"
    render_business_tab_bar("DDG", tab_png, width=524, height=72)
    overlay_images["tab_bar"] = str(tab_png)
    overlays.append(
        OverlayItem(
            id="tab_bar", kind="tab_bar", title="DDG Business Tabs",
            start_s=0.0, end_s=max(dur_s, 1.0),
            x=1376, y=20, width=524, height=72, is_persistent=True, asset_path=str(tab_png),
        )
    )

    # Auto-create mention cards snapped to 12-col grid (right side above subtitle band)
    for idx, m in enumerate(mentions):
        if m.is_private_business:
            continue
        first_ts = m.timestamps[0] if m.timestamps else 0.0
        card_start = round(first_ts, 2)
        card_end = round(min(max(dur_s, card_start + 5.0), card_start + 5.0), 2)
        snapped = snap_rect_to_grid(Rect(x=1400, y=140, width=460, height=160), anchor="right")
        ov_id = f"mention_{idx:02d}"
        card_png = proc_dir / f"{ov_id}.png"
        render_glass_panel(
            kicker="MENTIONED",
            title=m.official_name,
            body_lines=[m.url or "Official brand / product visual"],
            output_png=card_png,
            width=snapped.width,
            min_height=snapped.height,
        )
        overlay_images[ov_id] = str(card_png)
        m.on_screen = True
        m.overlay_id = ov_id
        overlays.append(
            OverlayItem(
                id=ov_id, kind="mention_card", title=m.official_name,
                start_s=card_start, end_s=card_end,
                x=snapped.x, y=snapped.y, width=snapped.width, height=snapped.height,
                priority=2, asset_path=str(card_png), extra={"official_name": m.official_name},
            )
        )

    blur_spans = stabilize_blur_spans(
        raw_blur_detections or [],
        pad_px=rules["G8_G8b_blurs_and_ocr"]["pad_px"],
        bridge_gap_s=rules["G8_G8b_blurs_and_ocr"]["bridge_gap_s"],
        downscale_factor=rules["G8_G8b_blurs_and_ocr"]["downscale_factor"],
        sigma=rules["G8_G8b_blurs_and_ocr"]["blur_sigma_min"],
    )

    # Default Streamlabs layout webcam + example window pane masks (excluding behind head)
    win_cfg_path = Path(studio_root) / "config" / "webcam_window_masks.example.json"
    webcam_rect = WebcamRect(0, 679, 537, 401)
    window_masks: list[WindowPaneMask] = []
    win_mask_png: Path | None = None
    if win_cfg_path.exists():
        wcfg = load_json(win_cfg_path)
        window_masks = [WindowPaneMask.from_dict(p) for p in wcfg.get("panes", [])]
        win_mask_png = build_webcam_window_mask_png(webcam_rect, window_masks, proc_dir / "webcam_windows_mask.png")

    ass_path = generate_ass_subtitles(transcript, proc_dir / "subtitles.ass", swear_spans=swear_spans, is_short=False)

    ollama = OllamaClient(
        base_url=settings["ollama"]["base_url"],
        text_model=settings["ollama"]["text_model"],
        vision_model=settings["ollama"]["vision_model"],
    )
    social_copy = generate_social_copy(jid, transcript, mentions, offline=offline, ollama=ollama)

    plan = EditPlan(
        job_id=jid,
        source_video=str(src_path),
        mode="longform" if mode in ("preview", "full") else mode,
        hud=hud,
        webcam_rect=webcam_rect,
        face_box=Rect(170, 740, 180, 210),
        blur_spans=blur_spans,
        window_masks=window_masks,
        overlays=overlays,
        cuts=gap_proposals,
        mentions=mentions,
        opusclip_candidates=hook_candidates,
        avatar=AvatarPlacement(enabled=True, composite_above_all_blurs=True),
        swear_spans=swear_spans,
        tv_icon_enabled=False,
        youtube_synthetic_flag=False,
        description_ai_line="Made with AI tools.",
        metadata={"social_copy": social_copy, "source_sha256": sha256_file(src_path)},
    )
    save_json(proc_dir / "edit_plan.json", plan.to_dict(), allowed_roots=allowed_roots)

    report = run_preflight(
        plan,
        source_probe=probe,
        transcript=transcript,
        rms_series=rms_series,
        raw_wav=raw_wav,
        proc_wav=proc_wav,
        numbers_check_log_path=numbers_log,
        output_dir=rev_dir,
        allowed_roots=allowed_roots,
        rules=rules,
    )

    rendered_files: dict[str, str] = {}
    if mode in ("preview", "full"):
        is_preview = mode == "preview"
        out_name = "preview.mp4" if is_preview else "master_1080p60.mp4"
        out_mp4 = rev_dir / out_name
        if is_preview:
            render_video_from_plan(
                plan, src_path, out_mp4, proc_dir,
                audio_override_wav=proc_wav,
                overlay_images=overlay_images,
                ass_path=ass_path,
                window_mask_png=win_mask_png,
                preview_mode=True,
                start_s=0.0,
                duration_s=min(60.0, max(1.0, dur_s)),
            )
        else:
            render_windows_and_concat(
                plan, src_path, dur_s, out_mp4, proc_dir,
                window_s=float(settings["ffmpeg"]["window_duration_s"]),
                audio_override_wav=proc_wav,
                overlay_images=overlay_images,
                ass_path=ass_path,
                window_mask_png=win_mask_png,
            )
        rendered_files[mode] = str(out_mp4)
        rendered_files[f"{mode}_sha256"] = sha256_file(out_mp4)

    elif mode == "shorts":
        s_ass = generate_ass_subtitles(transcript, proc_dir / "short_subtitles.ass", swear_spans=swear_spans, is_short=True)
        outro = Path(studio_root) / "assets" / "DDG Reel Outro 3s (1080x1920).mp4"
        short_out = rev_dir / "short_01.mp4"
        c0 = hook_candidates[0] if hook_candidates else None
        s_t0 = c0.mapped_start_s if (c0 and c0.mapped_start_s is not None) else 0.0
        s_t1 = c0.mapped_end_s if (c0 and c0.mapped_end_s is not None) else min(dur_s, 15.0)
        render_vertical_short(
            src_path, s_t0, max(s_t0 + 1.0, s_t1), short_out, proc_dir / "short_work",
            webcam_rect=webcam_rect.as_rect(),
            ass_path=s_ass,
            reel_outro_path=outro if outro.exists() else None,
        )
        rendered_files["short_01"] = str(short_out)

    elapsed_min = max(0.1, (time.monotonic() - t_start) / 60.0)
    log_job_time(f"{jid}:{mode}", gut_minutes=max(1.0, dur_s / 60.0), actual_minutes=elapsed_min, studio_root=studio_root, allowed_roots=allowed_roots)

    manifest = {
        "job_id": jid,
        "mode": mode,
        "status": "ready_for_review",
        "created_at_aest": now_aest_iso(),
        "source_video": str(src_path),
        "preflight_passed": report.passed,
        "rendered_files": rendered_files,
        "social_copy": social_copy,
        "hook_candidates": [c.to_dict() for c in hook_candidates],
        "cut_proposals": [c.to_dict() for c in gap_proposals],
        "mentions": [m.to_dict() for m in mentions],
    }
    save_json(rev_dir / "job_manifest.json", manifest, allowed_roots=allowed_roots)
    return manifest


def watch_inbox(studio_root: str | Path = STUDIO_ROOT, poll_s: int = 10) -> None:
    """Watch 01_Raw_Inbox for finished video drops, pausing automatically during UE5 / Streamlabs."""
    settings = load_settings(studio_root)
    f_root = Path(settings["footage_root"])
    inbox = f_root / settings["footage_subdirs"]["inbox"]
    inbox.mkdir(parents=True, exist_ok=True)
    pause_flag = Path(studio_root) / "logs" / "studio_paused.flag"
    seen_sizes: dict[Path, int] = {}

    print(f"[DDG Studio Watcher] Monitoring {inbox} (Ctrl+C to stop)...")
    while True:
        if pause_flag.exists():
            time.sleep(poll_s)
            continue
        busy, reason = is_gpu_busy_for_user(
            paused_processes=settings["gpu"]["pause_on_processes"],
            vram_threshold_mb=settings["gpu"]["vram_busy_threshold_mb"],
        )
        if busy:
            print(f"[Watcher] {reason} — waiting...")
            time.sleep(poll_s)
            continue

        for file in sorted(inbox.rglob("*")):
            if not file.is_file() or file.suffix.lower() not in VIDEO_EXTS:
                continue
            size = file.stat().st_size
            prev = seen_sizes.get(file)
            seen_sizes[file] = size
            if prev is None or prev != size or size == 0:
                continue  # Still copying
            print(f"[Watcher] Processing new raw video (Preview-First): {file.name}")
            try:
                run_job(file, mode="preview", offline=False, studio_root=studio_root)
                archive_dir = f_root / settings["footage_subdirs"]["archive"]
                archive_dir.mkdir(parents=True, exist_ok=True)
                file.replace(archive_dir / file.name)
            except Exception as exc:
                print(f"[Watcher] Failed on {file.name}: {exc}")
        time.sleep(poll_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DDG Local Bot Studio Pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_proc = sub.add_parser("process", help="Run pipeline on a single raw video")
    p_proc.add_argument("video", help="Path to source video inside F:/DDG_Video_Studio or studio")
    p_proc.add_argument("--mode", choices=["preview", "full", "shorts", "audit"], default="preview")
    p_proc.add_argument("--transcript", help="Optional pre-generated WhisperX word-timed JSON")
    p_proc.add_argument("--hud", help="Optional DDG Control HUD numbers JSON")
    p_proc.add_argument("--offline", action="store_true", help="Run without live Ollama/WhisperX")

    p_watch = sub.add_parser("watch", help="Watch 01_Raw_Inbox for raw footage drops")
    p_watch.add_argument("--poll", type=int, default=10)

    p_est = sub.add_parser("estimate", help="Print calibrated duration estimate")
    p_est.add_argument("gut_minutes", type=float)

    args = parser.parse_args(argv)
    if args.cmd == "process":
        res = run_job(
            args.video,
            mode=args.mode,
            transcript_json=args.transcript,
            hud_json=args.hud,
            offline=args.offline,
        )
        print(f"Job {res['job_id']} complete | preflight_passed={res['preflight_passed']}")
        return 0
    if args.cmd == "watch":
        watch_inbox(poll_s=args.poll)
        return 0
    if args.cmd == "estimate":
        print(predict_minutes(args.gut_minutes))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
