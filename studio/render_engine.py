"""FFmpeg 9.0.2 hardware-accelerated render engine (NVENC/x264 fallback, -/filter_complex, t-based enables, 60s resumable windows, Shorts)."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .blur_engine import cutout_webcam_from_box
from .models import EditPlan, Rect, STUDIO_ROOT, now_aest_iso


_CACHED_ENCODER: str | None = None


def escape_ffmpeg_filter_path(path: str | Path) -> str:
    """Escape Windows path for FFmpeg filter arguments like ass='C\\:/path/file.ass'."""
    p = str(Path(path).resolve()).replace("\\", "/")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    return p


def detect_best_encoder(preferred: str = "h264_nvenc", fallback: str = "libx264") -> str:
    """Probe whether NVENC works in current runtime; fall back cleanly to libx264 if unavailable."""
    global _CACHED_ENCODER
    if _CACHED_ENCODER is not None:
        return _CACHED_ENCODER
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:d=0.1",
        "-c:v",
        preferred,
        "-f",
        "null",
        "-",
    ]
    try:
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            _CACHED_ENCODER = preferred
            return preferred
    except Exception:
        pass
    _CACHED_ENCODER = fallback
    return fallback


def build_filter_script(
    plan: EditPlan,
    *,
    overlay_images: dict[str, str | Path] | None = None,
    ass_path: str | Path | None = None,
    window_mask_png: str | Path | None = None,
    avatar_png: str | Path | None = None,
    target_width: int = 1920,
    target_height: int = 1080,
) -> tuple[list[str], str]:
    """Construct FFmpeg 9.0.2 input args and -/filter_complex script obeying G6/G7/G8b."""
    overlay_images = overlay_images or {}
    extra_inputs: list[str] = []
    lines: list[str] = []

    # Input 0 = source video. Convert to rgba BEFORE odd-width blur crops (v3.2 FFmpeg gotcha).
    lines.append(f"[0:v]scale={target_width}:{target_height}:flags=lanczos,format=rgba[base0]")
    cur_v = "base0"
    step = 0

    # 1. Steady non-flickering privacy blurs (webcam rect cut out so blur NEVER bleeds into webcam)
    scale_x = target_width / 1920.0
    scale_y = target_height / 1080.0
    for b in plan.blur_spans:
        pieces = cutout_webcam_from_box(b.rect, plan.webcam_rect)
        for piece in pieces:
            rx = max(0, int(round(piece.x * scale_x)))
            ry = max(0, int(round(piece.y * scale_y)))
            rw = max(4, int(round(piece.width * scale_x)))
            rh = max(4, int(round(piece.height * scale_y)))
            rw = min(rw, target_width - rx)
            rh = min(rh, target_height - ry)
            if rw < 4 or rh < 4:
                continue

            step += 1
            main_a = f"bm_{step}"
            patch_raw = f"bp_{step}"
            patch_blur = f"bb_{step}"
            out_v = f"bo_{step}"

            down_w = max(2, int(round(rw / max(2, b.downscale_factor))))
            down_h = max(2, int(round(rh / max(2, b.downscale_factor))))
            sigma = max(2.0, float(b.sigma))
            en = f"between(t,{b.start_s:.3f},{b.end_s:.3f})"

            lines.append(f"[{cur_v}]split=2[{main_a}][{patch_raw}]")
            lines.append(
                f"[{patch_raw}]crop={rw}:{rh}:{rx}:{ry},"
                f"scale={down_w}:{down_h}:flags=bilinear,"
                f"gblur=sigma={sigma:.1f},"
                f"scale={rw}:{rh}:flags=bilinear[{patch_blur}]"
            )
            lines.append(f"[{main_a}][{patch_blur}]overlay={rx}:{ry}:format=rgb:enable='{en}'[{out_v}]")
            cur_v = out_v

    # 2. Webcam static per-pane window blur mask (G7: behind head stays sharp=0)
    if window_mask_png and Path(window_mask_png).exists() and plan.webcam_rect is not None:
        cam = plan.webcam_rect
        cx = max(0, int(round(cam.x * scale_x)))
        cy = max(0, int(round(cam.y * scale_y)))
        cw = max(8, (min(int(round(cam.width * scale_x)), target_width - cx) // 2) * 2)
        ch = max(8, (min(int(round(cam.height * scale_y)), target_height - cy) // 2) * 2)
        cy = min(cy, target_height - ch)
        cx = min(cx, target_width - cw)
        mask_idx = 1 + (len(extra_inputs) // 2)
        extra_inputs.extend(["-i", str(Path(window_mask_png).resolve())])

        step += 1
        main_w = f"wm_{step}"
        cam_src = f"wc_{step}"
        cam_blur = f"wcb_{step}"
        mask_s = f"wms_{step}"
        cam_masked = f"wcm_{step}"
        out_v = f"wo_{step}"
        lines.append(f"[{cur_v}]split=2[{main_w}][{cam_src}]")
        lines.append(f"[{cam_src}]format=rgba,crop={cw}:{ch}:{cx}:{cy},gblur=sigma=12.0,format=rgba[{cam_blur}]")
        lines.append(f"[{mask_idx}:v]scale={cw}:{ch},format=gray[{mask_s}]")
        lines.append(f"[{cam_blur}][{mask_s}]alphamerge[{cam_masked}]")
        lines.append(f"[{main_w}][{cam_masked}]overlay={cx}:{cy}:format=rgb[{out_v}]")
        cur_v = out_v

    # 3. Dramatic slow bottom-left zoom (3-5 s push anchored at [0, 1080])
    for z in plan.zooms:
        if z.is_dramatic and z.snap_back_s > z.peak_s > z.start_s:
            step += 1
            out_v = f"zm_{step}"
            push_dur = max(0.5, z.peak_s - z.start_s)
            z_delta = max(0.0, z.scale_max - 1.0)
            # Smooth eased push-in from start_s to peak_s, quick snap back at snap_back_s
            z_expr = (
                f"if(between(t,{z.start_s:.3f},{z.peak_s:.3f}),"
                f"1+{z_delta:.4f}*(0.5-0.5*cos(PI*(t-{z.start_s:.3f})/{push_dur:.3f})),"
                f"if(between(t,{z.peak_s:.3f},{z.snap_back_s:.3f}),{z.scale_max:.4f},1))"
            )
            lines.append(
                f"[{cur_v}]scale=w='trunc({target_width}*({z_expr})/2)*2':"
                f"h='trunc({target_height}*({z_expr})/2)*2':eval=frame,"
                f"crop={target_width}:{target_height}:0:ih-{target_height}[{out_v}]"
            )
            cur_v = out_v

    # 4. PNG Overlays (HUD, business tab bar, mention cards, agenda, factchecks)
    for ov in plan.overlays:
        img_path = overlay_images.get(ov.id) or ov.asset_path
        if not img_path or not Path(img_path).exists():
            continue
        inp_idx = 1 + (len(extra_inputs) // 2)
        extra_inputs.extend(["-i", str(Path(img_path).resolve())])

        ox = int(round(ov.x * scale_x))
        oy = int(round(ov.y * scale_y))
        ow = max(2, int(round(ov.width * scale_x)))
        oh = max(2, int(round(ov.height * scale_y)))

        step += 1
        ov_scaled = f"ovs_{step}"
        out_v = f"ovo_{step}"
        en = f"between(t,{ov.start_s:.3f},{ov.end_s:.3f})"
        lines.append(f"[{inp_idx}:v]scale={ow}:{oh},format=rgba[{ov_scaled}]")
        lines.append(f"[{cur_v}][{ov_scaled}]overlay={ox}:{oy}:format=rgb:enable='{en}'[{out_v}]")
        cur_v = out_v

    # 5. Burn ASS subtitles before final avatar layer
    if ass_path and Path(ass_path).exists():
        step += 1
        out_v = f"sub_{step}"
        esc_ass = escape_ffmpeg_filter_path(ass_path)
        lines.append(f"[{cur_v}]ass='{esc_ass}',format=rgba[{out_v}]")
        cur_v = out_v

    # 6. Composite Marketing/Freya Avatar STRICTLY LAST (ABOVE all blur layers, G6)
    if plan.avatar.enabled and avatar_png and Path(avatar_png).exists():
        inp_idx = 1 + (len(extra_inputs) // 2)
        extra_inputs.extend(["-i", str(Path(avatar_png).resolve())])
        av_size = max(32, int(round(140 * scale_x)))
        ax = int(round(plan.avatar.center_x * scale_x - av_size / 2))
        ay = int(round(plan.avatar.center_y * scale_y - av_size / 2))
        step += 1
        av_s = f"avs_{step}"
        out_v = f"avo_{step}"
        lines.append(f"[{inp_idx}:v]scale={av_size}:{av_size},format=rgba[{av_s}]")
        lines.append(f"[{cur_v}][{av_s}]overlay={ax}:{ay}:format=rgb[{out_v}]")
        cur_v = out_v

    lines.append(f"[{cur_v}]format=yuv420p[vout]")
    return extra_inputs, ";\n".join(lines)


def render_video_from_plan(
    plan: EditPlan,
    source_video: str | Path,
    output_mp4: str | Path,
    work_dir: str | Path,
    *,
    audio_override_wav: str | Path | None = None,
    overlay_images: dict[str, str | Path] | None = None,
    ass_path: str | Path | None = None,
    window_mask_png: str | Path | None = None,
    avatar_png: str | Path | None = None,
    preview_mode: bool = False,
    start_s: float | None = None,
    duration_s: float | None = None,
    prefer_encoder: str = "h264_nvenc",
) -> Path:
    """Render master or preview MP4 using FFmpeg 9 -/filter_complex file & audio normalization."""
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    out = Path(output_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)

    target_w = 1280 if preview_mode else 1920
    target_h = 720 if preview_mode else 1080
    encoder = detect_best_encoder(preferred=prefer_encoder, fallback="libx264")

    extra_inputs, filter_text = build_filter_script(
        plan,
        overlay_images=overlay_images,
        ass_path=ass_path,
        window_mask_png=window_mask_png,
        avatar_png=avatar_png,
        target_width=target_w,
        target_height=target_h,
    )
    script_path = wd / ("preview_filter.ffscript" if preview_mode else "master_filter.ffscript")
    script_path.write_text(filter_text, encoding="ascii")

    cmd: list[str] = ["ffmpeg", "-nostdin", "-y"]
    if start_s is not None:
        cmd.extend(["-ss", f"{start_s:.3f}"])
    if duration_s is not None:
        cmd.extend(["-t", f"{duration_s:.3f}"])
    cmd.extend(["-i", str(Path(source_video).resolve())])
    cmd.extend(extra_inputs)

    audio_map = "0:a?"
    if audio_override_wav and Path(audio_override_wav).exists():
        aud_idx = 1 + (len(extra_inputs) // 2)
        cmd.extend(["-i", str(Path(audio_override_wav).resolve())])
        audio_map = f"{aud_idx}:a"

    cmd.extend(["-/filter_complex", str(script_path), "-map", "[vout]", "-map", audio_map])
    if encoder == "h264_nvenc":
        if preview_mode:
            cmd.extend(["-c:v", "h264_nvenc", "-preset", "p3", "-b:v", "4M", "-maxrate", "8M", "-bufsize", "8M"])
        else:
            cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "11M", "-maxrate", "26M", "-bufsize", "22M"])
    else:
        if preview_mode:
            cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-b:v", "4M"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "fast", "-b:v", "11M", "-maxrate", "26M", "-bufsize", "22M"])

    cmd.extend(["-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])

    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed ({res.returncode}): {res.stderr[-700:]}")
    return out


def render_windows_and_concat(
    plan: EditPlan,
    source_video: str | Path,
    total_duration_s: float,
    output_mp4: str | Path,
    work_dir: str | Path,
    *,
    window_s: float = 60.0,
    audio_override_wav: str | Path | None = None,
    overlay_images: dict[str, str | Path] | None = None,
    ass_path: str | Path | None = None,
    window_mask_png: str | Path | None = None,
    avatar_png: str | Path | None = None,
) -> Path:
    """Render long episodes in resumable 60s windows (one FFmpeg at a time, PROGRESS.md) and concat."""
    wd = Path(work_dir)
    win_dir = wd / "windows"
    win_dir.mkdir(parents=True, exist_ok=True)
    progress_md = wd / "PROGRESS.md"

    n_windows = max(1, int(math.ceil(total_duration_s / window_s)))
    win_files: list[Path] = []

    if n_windows == 1:
        return render_video_from_plan(
            plan,
            source_video,
            output_mp4,
            wd,
            audio_override_wav=audio_override_wav,
            overlay_images=overlay_images,
            ass_path=ass_path,
            window_mask_png=window_mask_png,
            avatar_png=avatar_png,
            preview_mode=False,
        )

    for idx in range(n_windows):
        w_start = idx * window_s
        w_dur = min(window_s, max(0.1, total_duration_s - w_start))
        win_out = win_dir / f"win_{idx:04d}.mp4"
        win_files.append(win_out)
        if win_out.exists() and win_out.stat().st_size > 1024:
            continue
        render_video_from_plan(
            plan,
            source_video,
            win_out,
            win_dir / f"tmp_{idx:04d}",
            audio_override_wav=audio_override_wav,
            overlay_images=overlay_images,
            ass_path=ass_path,
            window_mask_png=window_mask_png,
            avatar_png=avatar_png,
            preview_mode=False,
            start_s=w_start,
            duration_s=w_dur,
        )
        progress_md.write_text(
            f"# Render Progress: {plan.job_id}\n- Updated: {now_aest_iso()}\n- Completed windows: {idx + 1}/{n_windows}\n",
            encoding="utf-8",
        )

    concat_list = wd / "concat_list.txt"
    concat_list.write_text(
        "\n".join(f"file '{str(p.resolve()).replace(chr(92), '/')}'" for p in win_files) + "\n",
        encoding="utf-8",
    )
    out = Path(output_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(out)]
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed: {res.stderr[-500:]}")
    return out


def render_vertical_short(
    source_video: str | Path,
    start_s: float,
    end_s: float,
    output_mp4: str | Path,
    work_dir: str | Path,
    *,
    webcam_rect: Rect | None = None,
    screen_crop_rect: Rect | None = None,
    ass_path: str | Path | None = None,
    reel_outro_path: str | Path | None = None,
    prefer_encoder: str = "h264_nvenc",
) -> Path:
    """Render 1080x1920 vertical Short on SOLID BLACK (#000000) with stacked webcam + screen context."""
    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    out = Path(output_mp4)
    out.parent.mkdir(parents=True, exist_ok=True)
    encoder = detect_best_encoder(preferred=prefer_encoder, fallback="libx264")
    dur = max(0.5, end_s - start_s)

    cam = webcam_rect or Rect(0, 679, 537, 401)
    ctx = screen_crop_rect or Rect(540, 120, 1340, 820)

    # Solid black 1080x1920 background; screen context above webcam ("profile cut")
    lines = [
        f"color=c=black:s=1080x1920:d={dur:.3f}:r=60[bg]",
        f"[0:v]split=2[s_cam][s_ctx]",
        f"[s_ctx]format=rgba,crop={ctx.width}:{ctx.height}:{ctx.x}:{ctx.y},scale=1040:-2:flags=lanczos[ctx_s]",
        f"[s_cam]format=rgba,crop={cam.width}:{cam.height}:{cam.x}:{cam.y},scale=960:-2:flags=lanczos,eq=contrast=1.04:saturation=1.08,unsharp=5:5:0.6[cam_s]",
        "[bg][ctx_s]overlay=(W-w)/2:220[p1]",
        "[p1][cam_s]overlay=(W-w)/2:980[vstacked]",
    ]
    cur = "vstacked"
    if ass_path and Path(ass_path).exists():
        lines.append(f"[{cur}]ass='{escape_ffmpeg_filter_path(ass_path)}'[vsub]")
        cur = "vsub"
    lines.append(f"[{cur}]format=yuv420p[vmain]")

    fc_path = wd / "short_filter.ffscript"
    fc_path.write_text(";\n".join(lines), encoding="ascii")

    body_out = wd / "short_body.mp4" if (reel_outro_path and Path(reel_outro_path).exists()) else out
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-ss", f"{start_s:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(Path(source_video).resolve()),
        "-/filter_complex", str(fc_path),
        "-map", "[vmain]",
        "-map", "0:a?",
        "-c:v", encoder,
        "-b:v", "8M",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "aac",
        "-b:a", "192k",
        str(body_out),
    ]
    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"Short render failed: {res.stderr[-600:]}")

    # Optionally append supplied 9:16 "DDG Reel Outro 3s" at 2x speed (1.5 s) strictly untouched in style
    if body_out != out and reel_outro_path and Path(reel_outro_path).exists():
        outro_2x = wd / "outro_2x.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-i", str(Path(reel_outro_path).resolve()),
                "-vf", "setpts=0.5*PTS,scale=1080:1920,format=yuv420p",
                "-af", "atempo=2.0", "-t", "1.5",
                "-c:v", encoder, "-c:a", "aac", str(outro_2x),
            ],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=True,
        )
        clist = wd / "short_concat.txt"
        clist.write_text(
            f"file '{str(body_out.resolve()).replace(chr(92), '/')}'\nfile '{str(outro_2x.resolve()).replace(chr(92), '/')}'\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(clist), "-c", "copy", str(out)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=True,
        )
    return out
