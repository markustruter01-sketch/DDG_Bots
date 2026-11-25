"""Comprehensive End-to-End Test Suite for DDG Local Bot Studio (G0-G11, Night Glass, FFmpeg 9, Dashboard)."""

from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path

from PIL import Image

STUDIO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO_ROOT))

from dashboard.server import create_server, dispatch_http_request, make_handler
from studio.audio_engine import (
    apply_swear_static_censor,
    audit_g5b_no_privacy_mutes,
    compensate_delay_samples,
    detect_swears,
    estimate_audio_delay_ms,
    find_nearest_silence_boundary,
    measure_rms_10ms,
    propose_long_gaps,
)
from studio.blur_engine import (
    audit_g8b_blur_stability,
    build_webcam_window_mask_png,
    cutout_webcam_from_box,
    find_sensitive_ocr_hits,
    generate_before_after_strip,
    stabilize_blur_spans,
)
from studio.calibration import log_job_time, predict_minutes
from studio.layout_grid import (
    align_check,
    duration_and_wild_cap_check,
    face_clearance_check,
    overlap_and_area_check,
    snap_rect_to_grid,
)
from studio.media_probe import check_source_quality, probe_media
from studio.mentions import audit_g11_mentions, scan_mentions
from studio.models import (
    AvatarPlacement,
    CutProposal,
    EditPlan,
    HudNumbers,
    OpusClipCandidate,
    OverlayItem,
    Rect,
    SecurityError,
    Transcript,
    WebcamRect,
    WindowPaneMask,
    WordTimestamp,
    ZoomEvent,
    assert_in_allowed_roots,
)
from studio.night_glass_gfx import (
    contains_emoji,
    generate_ass_subtitles,
    render_agenda_widget,
    render_business_tab_bar,
    render_factcheck_card,
    render_glass_panel,
    render_hud_bar,
)
from studio.opusclip_bridge import (
    OpusClipPolicyGuard,
    PolicyViolationError,
    local_hook_scorer,
    map_opusclip_candidates,
)
from studio.pipeline import run_job
from studio.preflight import run_preflight
from studio.render_engine import render_vertical_short, render_video_from_plan
from studio.scheduler import (
    build_heimdall_daily_list,
    queue_failure_for_daily_digest,
    validate_marketing_mode_schedule,
)


def _write_synth_wav(path: Path, segments: list[tuple[float, float, float]], total_s: float, sr: int = 48000) -> Path:
    """Create deterministic 16-bit mono PCM WAV with speech-like tone bursts (freq_hz) or silence (freq=0)."""
    n_total = int(round(total_s * sr))
    samples = [0] * n_total
    for start_s, end_s, freq_hz in segments:
        if freq_hz <= 0:
            continue
        i0 = max(0, int(round(start_s * sr)))
        i1 = min(n_total, int(round(end_s * sr)))
        for i in range(i0, i1):
            t = i / sr
            val = 0.35 * math.sin(2.0 * math.pi * freq_hz * t)
            samples[i] = int(val * 32767)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def _make_synth_mp4(path: Path, width: int, height: int, fps: int, dur_s: float, wav_path: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={dur_s:.2f}",
    ]
    if wav_path is not None:
        cmd.extend(["-i", str(wav_path)])
    else:
        cmd.extend(["-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate=48000:d={dur_s:.2f}"])
    cmd.extend([
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(path),
    ])
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"Synthetic MP4 creation failed: {res.stderr[-400:]}")
    return path


class TestDDGLocalBotStudioE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_root = STUDIO_ROOT / "logs" / "e2e_test_workspace"
        if cls.tmp_root.exists():
            shutil.rmtree(cls.tmp_root, ignore_errors=True)
        cls.tmp_root.mkdir(parents=True, exist_ok=True)
        cls.footage_root = cls.tmp_root / "DDG_Video_Studio"
        for sub in ("01_Raw_Inbox", "02_Processing", "03_Ready_For_Review", "04_Approved_Exports", "05_Archive"):
            (cls.footage_root / sub).mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.tmp_root.exists():
            shutil.rmtree(cls.tmp_root, ignore_errors=True)

    def test_01_path_jail_and_isolation(self) -> None:
        allowed = [STUDIO_ROOT, self.footage_root]
        ok_path = assert_in_allowed_roots(STUDIO_ROOT / "config" / "rules.json", allowed)
        self.assertTrue(ok_path.exists())
        with self.assertRaises(SecurityError):
            assert_in_allowed_roots(r"C:\Users\User\Desktop\DDG\DDG Finance\secret.json", allowed)
        with self.assertRaises(SecurityError):
            assert_in_allowed_roots(r"C:\Users\User\Desktop\DDG\DDG_GodsEyeView\package.json", allowed)

    def test_02_g0_hud_balance_and_night_glass_rendering(self) -> None:
        hud = HudNumbers(
            followers=811, views=108400, likes=435,
            expenses=2711.40, gross_revenue=956.90, debt=1754.50,
            charity_deducted=33.00, net_profit=-1787.50,
        )
        ok, _ = hud.is_balanced()
        self.assertTrue(ok)

        hud_png, meta = render_hud_bar(hud, self.tmp_root / "hud.png", width=1340, height=72)
        tab_png = render_business_tab_bar("DDG", self.tmp_root / "tab.png", width=524, height=72)
        self.assertTrue(hud_png.exists())
        self.assertTrue(tab_png.exists())
        self.assertTrue(meta["text_fit_ok"])
        with Image.open(hud_png) as h_im, Image.open(tab_png) as t_im:
            self.assertEqual(h_im.size[1], t_im.size[1])

        bad_hud = HudNumbers(
            followers=10, views=10, likes=1,
            expenses=2711.40, gross_revenue=956.90, debt=999.00,
            charity_deducted=33.00, net_profit=-1787.50,
        )
        ok_bad, _ = bad_hud.is_balanced()
        self.assertFalse(ok_bad)

        card_png, cmeta = render_glass_panel(
            kicker="QUICK CONTEXT",
            title="MUNBYN Thermal Printer Setup and Integration Check",
            body_lines=["Official logo + product visual", "https://www.munbyn.com"],
            footer="Verified source",
            output_png=self.tmp_root / "card.png",
            width=460,
        )
        self.assertTrue(card_png.exists())
        self.assertTrue(cmeta["text_fit_ok"])
        self.assertGreaterEqual(cmeta["title_size"], 30)

        fc_png, fmeta = render_factcheck_card(
            1, "Claude API is free", "API is pay-as-you-go", "anthropic.com", self.tmp_root / "fc.png"
        )
        self.assertTrue(fc_png.exists() and fmeta["text_fit_ok"])

        ag_png, ameta = render_agenda_widget(
            ["Intro", "Cattle Dog Coffee", "DDG Finance", "Hypest", "Threads of Empire", "Freya Edit"],
            current_index=2,
            side_quest="Grok Bot usage audit",
            output_png=self.tmp_root / "agenda.png",
        )
        self.assertTrue(ag_png.exists() and ameta["text_fit_ok"])

        self.assertTrue(contains_emoji("Test 🔥"))
        with self.assertRaises(ValueError):
            render_glass_panel(title="No 🔥 emojis", body_lines=["clean"], output_png=self.tmp_root / "bad.png")

    def test_03_g1_source_probe(self) -> None:
        v1080 = _make_synth_mp4(self.tmp_root / "src_1080p60.mp4", 1920, 1080, 60, 0.5)
        v720 = _make_synth_mp4(self.tmp_root / "src_720p60.mp4", 1280, 720, 60, 0.5)

        p1080 = probe_media(v1080)
        p720 = probe_media(v720)
        self.assertTrue(check_source_quality(p1080).passed)
        self.assertFalse(check_source_quality(p720).passed)

    def test_04_g5b_swear_only_static_and_sync_compensation(self) -> None:
        words = [
            WordTimestamp("cattle", 0.30, 0.70),
            WordTimestamp("dog", 0.75, 1.10),
            WordTimestamp("fuck", 1.20, 1.60),
            WordTimestamp("damn", 1.70, 2.10),
            WordTimestamp("bullshit", 2.20, 2.70),
            WordTimestamp("replit", 2.80, 3.30),
            WordTimestamp("mishit", 3.40, 3.80),
        ]
        tr = Transcript(source_path="synth.wav", words=words)
        swears = detect_swears(tr)
        swear_words = [s["word"] for s in swears]
        self.assertEqual(swear_words, ["fuck", "bullshit"])

        raw_wav = _write_synth_wav(
            self.tmp_root / "speech_raw.wav",
            [(w.start, w.end, 330.0) for w in words],
            total_s=4.2,
        )
        proc_wav = apply_swear_static_censor(
            raw_wav, self.tmp_root / "speech_clean.wav", swears, gain=0.05992, fade_ms=30
        )
        g5b_pass = audit_g5b_no_privacy_mutes(raw_wav, proc_wav, tr, swears)
        self.assertTrue(g5b_pass.passed, g5b_pass.summary)

        # Now inject illegal non-swear privacy mute on 'cattle' (0.30..0.70)
        bad_wav = _write_synth_wav(
            self.tmp_root / "speech_privacy_muted.wav",
            [(w.start, w.end, 330.0) for w in words if w.word != "cattle"],
            total_s=4.2,
        )
        g5b_fail = audit_g5b_no_privacy_mutes(raw_wav, bad_wav, tr, swears)
        self.assertFalse(g5b_fail.passed)

        # Verify 25 ms afftdn delay compensation
        sr = 48000
        with wave.open(str(raw_wav), "rb") as wf:
            raw_bytes = wf.readframes(wf.getnframes())
        raw_samps = list(struct.unpack(f"<{len(raw_bytes)//2}h", raw_bytes))
        shift = int(0.025 * sr)
        delayed = [0] * shift + raw_samps[:-shift]
        delayed_wav = self.tmp_root / "delayed25.wav"
        with wave.open(str(delayed_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(delayed)}h", *delayed))
        self.assertGreaterEqual(abs(estimate_audio_delay_ms(raw_wav, delayed_wav)), 20.0)
        comp_wav = compensate_delay_samples(delayed_wav, self.tmp_root / "comp25.wav", delay_ms=25.0)
        self.assertLessEqual(abs(estimate_audio_delay_ms(raw_wav, comp_wav)), 3.0)

    def test_05_g10_10ms_silence_cut_snapping(self) -> None:
        wav = _write_synth_wav(
            self.tmp_root / "gaps.wav",
            [(0.5, 1.5, 300.0), (2.3, 3.0, 300.0), (8.0, 9.0, 300.0)],
            total_s=9.5,
        )
        rms = measure_rms_10ms(wav)
        tr = Transcript(
            source_path="gaps.wav",
            words=[
                WordTimestamp("hello", 0.5, 1.5),
                WordTimestamp("world", 2.3, 3.0),  # 0.8s short pause before this -> NEVER propose!
                WordTimestamp("back", 8.0, 9.0),   # 5.0s long gap -> propose!
            ],
        )
        proposals = propose_long_gaps(tr, rms, min_gap_s=4.0)
        self.assertEqual(len(proposals), 1)
        self.assertGreaterEqual(proposals[0].duration, 4.0)

        snapped_t, snapped_db = find_nearest_silence_boundary(rms, 1.45, pad_ms=120)
        self.assertGreaterEqual(snapped_t, 1.50)
        self.assertLessEqual(snapped_db, -42.0)

        # Approving a short pause or mid-word boundary must fail G10
        bad_plan = EditPlan(
            job_id="bad_cut",
            source_video="gaps.wav",
            cuts=[CutProposal("c1", 1.0, 2.0, "short pause", approved=True, is_short_pause=True)],
        )
        rep = run_preflight(bad_plan, rms_series=rms)
        g10 = next(g for g in rep.gates if g.gate_id == "G10_CUTS")
        self.assertFalse(g10.passed)

    def test_06_g11_mentions_audit(self) -> None:
        tr = Transcript(
            source_path="m.wav",
            words=[
                WordTimestamp("This", 1.0, 1.2),
                WordTimestamp("Mynbyn", 1.25, 1.6),
                WordTimestamp("printer", 1.65, 2.0),
                WordTimestamp("and", 2.1, 2.2),
                WordTimestamp("Replit", 2.3, 2.7),
                WordTimestamp("plus", 2.8, 3.0),
                WordTimestamp("Threads", 3.1, 3.4),
                WordTimestamp("of", 3.45, 3.55),
                WordTimestamp("Empire.", 3.6, 4.0),
            ],
        )
        mentions = scan_mentions(tr)
        names = {m.official_name for m in mentions}
        self.assertIn("MUNBYN", names)
        self.assertIn("Replit", names)
        self.assertIn("Threads of Empire", names)

        plan = EditPlan(job_id="m_test", source_video="m.wav", mentions=mentions)
        self.assertFalse(audit_g11_mentions(plan).passed)

        for idx, m in enumerate(plan.mentions):
            ov_id = f"ov_m_{idx}"
            plan.overlays.append(
                OverlayItem(ov_id, "mention_card", m.official_name, 1.0 + idx * 6.0, 6.0 + idx * 6.0, 1420, 144, 480, 200)
            )
            m.overlay_id = ov_id
            m.on_screen = True
        self.assertTrue(audit_g11_mentions(plan).passed)

    def test_07_opusclip_bridge_and_local_fallback(self) -> None:
        guard = OpusClipPolicyGuard(credits_remaining=261, warn_over_credits=140)
        b_big = guard.check_credit_budget(160.0)
        self.assertTrue(b_big["requires_markus_approval"])
        self.assertTrue(b_big["exceeds_warn_threshold"])

        b_ok = guard.check_credit_budget(30.0)
        self.assertFalse(b_ok["requires_markus_approval"])

        with self.assertRaises(PolicyViolationError):
            guard.validate_submission(is_raw_source=False, is_private=True, analysis_only=True)
        with self.assertRaises(PolicyViolationError):
            guard.validate_submission(is_raw_source=True, is_private=False, analysis_only=True)
        with self.assertRaises(PolicyViolationError):
            guard.block_raw_publish()

        wav = _write_synth_wav(self.tmp_root / "opus.wav", [(1.0, 2.5, 330.0), (3.2, 4.4, 330.0)], total_s=5.5)
        rms = measure_rms_10ms(wav)
        tr = Transcript(
            source_path="opus.wav",
            words=[
                WordTimestamp("Building", 1.0, 1.4),
                WordTimestamp("zero", 1.45, 1.8),
                WordTimestamp("cost", 1.85, 2.2),
                WordTimestamp("bots!", 2.25, 2.5),
                WordTimestamp("Next", 3.2, 3.6),
                WordTimestamp("step.", 3.65, 4.4),
            ],
        )
        cands = [OpusClipCandidate("oc1", "Zero cost bots", "Building zero cost bots!", 94.0)]
        mapped = map_opusclip_candidates(cands, tr, rms_series=rms)
        self.assertIsNotNone(mapped[0].mapped_start_s)
        self.assertLessEqual(mapped[0].start_rms_db, -42.0)
        self.assertLessEqual(mapped[0].end_rms_db, -42.0)

        local_cands = local_hook_scorer(tr, rms_series=rms)
        self.assertTrue(len(local_cands) >= 1)
        self.assertFalse(local_cands[0].approved)

    def test_08_g7_g8_g8b_blur_stability_and_window_mask(self) -> None:
        raw_dets = [
            {"group": "chat_box", "label": "Claude sidebar", "start_s": 1.0, "end_s": 3.0, "x": 100, "y": 200, "width": 200, "height": 400},
            {"group": "chat_box", "label": "Claude sidebar", "start_s": 3.4, "end_s": 6.0, "x": 120, "y": 210, "width": 210, "height": 420},
        ]
        spans = stabilize_blur_spans(raw_dets, pad_px=6, bridge_gap_s=1.0)
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0].start_s, spans[0].end_s), (1.0, 6.0))
        self.assertEqual((spans[0].x, spans[0].y), (94, 194))

        cam = WebcamRect(0, 679, 537, 401)
        big_box = Rect(0, 500, 700, 500)
        pieces = cutout_webcam_from_box(big_box, cam)
        self.assertTrue(all(not p.intersects(cam.as_rect()) for p in pieces))

        panes = [
            WindowPaneMask("left", False, [[0.05, 0.05], [0.25, 0.05], [0.25, 0.55], [0.05, 0.55]]),
            WindowPaneMask("behind_head", True, [[0.35, 0.05], [0.65, 0.05], [0.65, 0.55], [0.35, 0.55]]),
        ]
        mask_png = build_webcam_window_mask_png(cam, panes, self.tmp_root / "win_mask.png")
        with Image.open(mask_png) as m_img:
            self.assertEqual(m_img.getpixel((int(0.15 * cam.width), int(0.30 * cam.height))), 255)
            self.assertEqual(m_img.getpixel((int(0.50 * cam.width), int(0.30 * cam.height))), 0)

        self.assertTrue(audit_g8b_blur_stability(spans, webcam_rect=cam).passed)

        spans[0].dropped_frames = 1
        self.assertFalse(audit_g8b_blur_stability(spans, webcam_rect=cam).passed)
        spans[0].dropped_frames = 0

        hits = find_sensitive_ocr_hits(
            ["Welcome someone@example.com"],
            sensitive_terms=["someone"],
            sensitive_regexes=[r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"],
        )
        self.assertTrue(len(hits) >= 1)

        # Before/after strip check
        b_img = Image.new("RGB", (320, 180), (40, 40, 40))
        a_img = Image.new("RGB", (320, 180), (20, 21, 24))
        b_p, a_p = self.tmp_root / "before.png", self.tmp_root / "after.png"
        b_img.save(b_p)
        a_img.save(a_p)
        strip = generate_before_after_strip(b_p, a_p, self.tmp_root / "strip.png")
        with Image.open(strip) as s_im:
            self.assertEqual(s_im.size, (652, 180))

    def test_09_g4_g5_g6_grid_clearance_and_avatar_layering(self) -> None:
        snapped = snap_rect_to_grid(Rect(1400, 125, 455, 220), anchor="right")
        ov = OverlayItem("ov1", "mention_card", "MUNBYN", 1.0, 8.0, snapped.x, snapped.y, snapped.width, snapped.height)
        hud = OverlayItem("hud", "hud", "HUD", 0.0, 20.0, 20, 20, 1340, 72, is_persistent=True)
        tab = OverlayItem("tab", "tab_bar", "Tabs", 0.0, 20.0, 1376, 20, 524, 72, is_persistent=True)

        self.assertTrue(align_check([hud, tab, ov]).passed)
        self.assertEqual(face_clearance_check([ov], Rect(170, 740, 180, 210)), [])
        issues, ratio = overlap_and_area_check([hud, tab, ov])
        self.assertEqual(issues, [])
        self.assertLess(ratio, 0.75)
        self.assertEqual(duration_and_wild_cap_check([ov], mode="longform"), [])

        # Violate avatar flip & below-blur layering + bad zoom anchor
        bad_plan = EditPlan(
            job_id="g6_bad",
            source_video="v.mp4",
            avatar=AvatarPlacement(enabled=True, flipped=True, composite_above_all_blurs=False),
            zooms=[ZoomEvent("z1", 1.0, 2.0, 3.0, anchor=[960, 540])],
        )
        rep = run_preflight(bad_plan)
        g6 = next(g for g in rep.gates if g.gate_id == "G6_AVATAR_ZOOM")
        self.assertFalse(g6.passed)

    def test_10_real_ffmpeg_pipeline_and_short_render(self) -> None:
        wav = _write_synth_wav(
            self.tmp_root / "pipe_audio.wav",
            [(0.2, 0.8, 320.0), (1.0, 1.5, 440.0), (1.7, 2.4, 300.0)],
            total_s=2.8,
        )
        src_mp4 = _make_synth_mp4(self.footage_root / "01_Raw_Inbox" / "ep_test.mp4", 1920, 1080, 60, 2.8, wav_path=wav)

        tr_path = self.tmp_root / "ep_test_transcript.json"
        tr = Transcript(
            source_path=str(src_mp4),
            words=[
                WordTimestamp("Testing", 0.2, 0.5),
                WordTimestamp("MUNBYN", 0.55, 0.8),
                WordTimestamp("fuck", 1.0, 1.4),
                WordTimestamp("clean", 1.7, 2.3),
            ],
        )
        tr_path.write_text(json.dumps(tr.to_dict()), encoding="utf-8")

        hud_path = self.tmp_root / "ep_hud.json"
        hud_path.write_text(
            json.dumps(
                HudNumbers(
                    followers=811, views=108400, likes=435,
                    expenses=2711.40, gross_revenue=956.90, debt=1754.50,
                    charity_deducted=33.0, net_profit=-1787.50,
                ).to_dict()
            ),
            encoding="utf-8",
        )

        # Note: MUNBYN overlay is >=4.5s; extend synthetic duration for card check or verify preview render
        manifest = run_job(
            src_mp4,
            job_id="ep_e2e_01",
            mode="preview",
            transcript_json=tr_path,
            hud_json=hud_path,
            raw_blur_detections=[
                {"group": "panel", "label": "Left chat", "start_s": 0.0, "end_s": 2.5, "x": 40, "y": 140, "width": 250, "height": 420}
            ],
            offline=True,
            studio_root=STUDIO_ROOT,
            footage_root=self.footage_root,
        )
        self.assertTrue(manifest["preflight_passed"], f"Preflight failed unexpectedly: {manifest}")
        preview_mp4 = Path(manifest["rendered_files"]["preview"])
        self.assertTrue(preview_mp4.exists())
        p_out = probe_media(preview_mp4)
        self.assertEqual((p_out["video"]["width"], p_out["video"]["height"]), (1280, 720))

        # Verify master 1080p render with explicit avatar PNG above blur + dramatic bottom-left zoom
        plan = EditPlan.from_dict(
            json.loads((self.footage_root / "02_Processing" / "ep_e2e_01" / "edit_plan.json").read_text(encoding="utf-8"))
        )
        plan.zooms = [ZoomEvent("z_dram", 0.2, 2.2, 2.7, scale_max=1.12, anchor=[0, 1080], is_dramatic=True)]
        master_mp4 = render_video_from_plan(
            plan,
            src_mp4,
            self.tmp_root / "master_test.mp4",
            self.tmp_root / "master_work",
            overlay_images={"hud_bar": str(self.footage_root / "02_Processing" / "ep_e2e_01" / "hud_bar.png")},
            ass_path=self.footage_root / "02_Processing" / "ep_e2e_01" / "subtitles.ass",
            avatar_png=STUDIO_ROOT / "assets" / "DDG_Logo_New.png",
            preview_mode=False,
        )
        pm = probe_media(master_mp4)
        self.assertEqual((pm["video"]["width"], pm["video"]["height"]), (1920, 1080))

        # Verify 1080x1920 solid-black vertical Short render
        short_ass = generate_ass_subtitles(tr, self.tmp_root / "short.ass", swear_spans=plan.swear_spans, is_short=True)
        short_mp4 = render_vertical_short(
            src_mp4, 0.2, 2.4, self.tmp_root / "short_test.mp4", self.tmp_root / "short_work", ass_path=short_ass
        )
        ps = probe_media(short_mp4)
        self.assertEqual((ps["video"]["width"], ps["video"]["height"]), (1080, 1920))

    def test_11_night_glass_dashboard_http(self) -> None:
        # Isolated studio root for dashboard state files so tests keep real logs clean
        dash_root = self.tmp_root / "dash_studio"
        shutil.copytree(STUDIO_ROOT / "config", dash_root / "config")
        shutil.copytree(STUDIO_ROOT / "assets", dash_root / "assets")
        shutil.copytree(STUDIO_ROOT / "dashboard", dash_root / "dashboard")
        (dash_root / "logs").mkdir(parents=True, exist_ok=True)

        with self.assertRaises(PermissionError):
            create_server(host="0.0.0.0", port=0, studio_root=dash_root, footage_root=self.footage_root)

        # Ensure a passing job and a failing job exist in 03_Ready_For_Review
        rev = self.footage_root / "03_Ready_For_Review"
        fail_dir = rev / "job_fail"
        fail_dir.mkdir(parents=True, exist_ok=True)
        (fail_dir / "job_manifest.json").write_text(
            json.dumps({"job_id": "job_fail", "mode": "preview", "preflight_passed": False, "rendered_files": {}}),
            encoding="utf-8",
        )
        (fail_dir / "preflight_report.json").write_text(
            json.dumps({"job_id": "job_fail", "passed": False, "gates": [{"gate_id": "G8b_BLUR_STABILITY", "passed": False, "summary": "Flicker"}]}),
            encoding="utf-8",
        )

        srv = create_server(host="127.0.0.1", port=0, studio_root=dash_root, footage_root=self.footage_root)
        srv.server_close()

        handler_cls = make_handler(dash_root, self.footage_root)

        # Standalone HTML file exists and passes strict Night Glass v6.1 token checks
        self.assertTrue((STUDIO_ROOT / "dashboard" / "index.html").is_file())
        code, _, body = dispatch_http_request(handler_cls, "GET", "/")
        self.assertEqual(code, 200)
        html = body.decode("utf-8")
        self.assertIn("DDG", html)
        self.assertIn("#141518", html)
        self.assertIn("--ng-ice: #6cc7f0", html)
        self.assertIn("--ng-amber: #f5a524", html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("ng-pill", html)
        self.assertIn('role="switch"', html)
        self.assertIn("tabular-nums", html)
        self.assertNotIn("#ff6b6b", html.lower())

        # Verify ZERO raw hex colors appear inside <style> outside :root token block
        style_m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
        self.assertIsNotNone(style_m)
        css_after_root = re.sub(r":root\s*\{.*?\}", "", style_m.group(1), flags=re.DOTALL)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}", css_after_root), [])

        # Asset serving & traversal protection
        code, hdrs, asset_bytes = dispatch_http_request(handler_cls, "GET", "/assets/DDG_Logo_New.png")
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get("content-type"), "image/png")
        self.assertTrue(asset_bytes.startswith(b"\x89PNG"))
        code, _, _ = dispatch_http_request(handler_cls, "GET", "/assets/../config/rules.json")
        self.assertEqual(code, 404)

        # Bot management & local chat APIs
        code, _, bots_body = dispatch_http_request(handler_cls, "GET", "/api/bots")
        self.assertEqual(code, 200)
        bots = json.loads(bots_body.decode("utf-8"))["bots"]
        self.assertEqual(len(bots), 9)
        self.assertEqual(sum(1 for b in bots if b["active"]), 3)

        code, _, tog_body = dispatch_http_request(handler_cls, "POST", "/api/bots/Mimir/toggle", b"{}")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(tog_body.decode("utf-8"))["active"])
        code, _, tog_back = dispatch_http_request(handler_cls, "POST", "/api/bots/Mimir/toggle", b"{}")
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(tog_back.decode("utf-8"))["active"])

        code, _, chat_body = dispatch_http_request(
            handler_cls,
            "POST",
            "/api/bots/Heimdall/chat",
            json.dumps({"message": "Give daily status", "offline": True}).encode("utf-8"),
        )
        self.assertEqual(code, 200)
        self.assertIn("Heimdall", json.loads(chat_body.decode("utf-8"))["reply"])
        code, _, bots_after = dispatch_http_request(handler_cls, "GET", "/api/bots")
        heim = next(b for b in json.loads(bots_after.decode("utf-8"))["bots"] if b["name"] == "Heimdall")
        self.assertEqual(len(heim["history"]), 2)

        # Inbox, OpusClip guard, schedule, Heimdall brief & system health APIs
        code, _, inbox_body = dispatch_http_request(handler_cls, "GET", "/api/inbox")
        self.assertEqual(code, 200)
        self.assertIn("files", json.loads(inbox_body.decode("utf-8")))

        code, _, oc_body = dispatch_http_request(
            handler_cls, "POST", "/api/opusclip/check", json.dumps({"source_minutes": 160}).encode("utf-8")
        )
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(oc_body.decode("utf-8"))["requires_markus_approval"])

        code, _, sched_body = dispatch_http_request(handler_cls, "GET", "/api/schedule")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(sched_body.decode("utf-8"))["valid"])

        code, _, brief_body = dispatch_http_request(handler_cls, "POST", "/api/heimdall/brief", b"{}")
        self.assertEqual(code, 200)
        self.assertLessEqual(len(json.loads(brief_body.decode("utf-8"))["items"]), 5)

        code, _, sys_body = dispatch_http_request(handler_cls, "GET", "/api/system")
        self.assertEqual(code, 200)
        self.assertIn("assets", json.loads(sys_body.decode("utf-8")))

        # Job list, 409 approval gate block, 200 export, tweak, and pause toggle
        code, _, body = dispatch_http_request(handler_cls, "GET", "/api/jobs")
        self.assertEqual(code, 200)
        jobs_data = json.loads(body.decode("utf-8"))
        ids = {j["job_id"] for j in jobs_data["jobs"]}
        self.assertIn("job_fail", ids)

        code, _, body = dispatch_http_request(handler_cls, "POST", "/api/jobs/job_fail/approve", b"{}")
        self.assertEqual(code, 409)
        self.assertIn("failed_gates", json.loads(body.decode("utf-8")))

        self.assertTrue((rev / "ep_e2e_01" / "preflight_report.json").exists())
        code, _, _ = dispatch_http_request(handler_cls, "POST", "/api/jobs/ep_e2e_01/approve", b"{}")
        self.assertEqual(code, 200)
        self.assertTrue((self.footage_root / "04_Approved_Exports" / "ep_e2e_01" / "job_manifest.json").exists())

        code, _, _ = dispatch_http_request(
            handler_cls, "POST", "/api/jobs/ep_e2e_01/tweak",
            json.dumps({"note": "", "youtube_title": "DDG Ep Test"}).encode("utf-8"),
        )
        self.assertEqual(code, 200)
        code, _, b_pause = dispatch_http_request(handler_cls, "POST", "/api/pause", b"{}")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(b_pause.decode("utf-8"))["paused"])
        code, _, b_resume = dispatch_http_request(handler_cls, "POST", "/api/pause", b"{}")
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(b_resume.decode("utf-8"))["paused"])

    def test_12_scheduler_and_calibration(self) -> None:
        ok, issues = validate_marketing_mode_schedule()
        self.assertTrue(ok, f"Schedule errors: {issues}")
        q = queue_failure_for_daily_digest("Marketing", "daily_brief_5pm", "Simulated test failure", studio_root=self.tmp_root)
        self.assertTrue(q.exists())
        digest = build_heimdall_daily_list(studio_root=self.tmp_root)
        self.assertLessEqual(len(digest["items"]), 5)

        log_job_time("test_ep", gut_minutes=10.0, actual_minutes=15.0, studio_root=self.tmp_root)
        pred = predict_minutes(10.0, studio_root=self.tmp_root)
        self.assertGreaterEqual(pred["predicted_minutes"], 10.0)


if __name__ == "__main__":
    unittest.main()
