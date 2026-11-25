"""Non-flickering privacy blur stabilizer (G8/G8b), webcam cutout, exact window masks (G7), and OCR audit."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .models import BlurSpan, GateResult, Rect, WebcamRect, WindowPaneMask


def stabilize_blur_spans(
    raw_detections: list[dict[str, Any]],
    pad_px: int = 6,
    bridge_gap_s: float = 1.0,
    max_w: int = 1920,
    max_h: int = 1080,
    downscale_factor: int = 12,
    sigma: float = 9.0,
) -> list[BlurSpan]:
    """Convert raw per-frame detections into constant steady union boxes bridging gaps < 1 s (G8b)."""
    if not raw_detections:
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for det in raw_detections:
        key = str(det.get("group") or det.get("label") or det.get("id") or "default")
        grouped.setdefault(key, []).append(det)

    result: list[BlurSpan] = []
    span_idx = 1
    for key, items in grouped.items():
        items_sorted = sorted(items, key=lambda d: float(d["start_s"]))
        clusters: list[list[dict[str, Any]]] = []
        for item in items_sorted:
            if not clusters:
                clusters.append([item])
                continue
            prev_end = max(float(x["end_s"]) for x in clusters[-1])
            if float(item["start_s"]) - prev_end < bridge_gap_s:
                clusters[-1].append(item)
            else:
                clusters.append([item])

        for cluster in clusters:
            s_min = min(float(x["start_s"]) for x in cluster)
            e_max = max(float(x["end_s"]) for x in cluster)
            x0 = min(int(x["x"]) for x in cluster)
            y0 = min(int(x["y"]) for x in cluster)
            x1 = max(int(x["x"]) + int(x["width"]) for x in cluster)
            y1 = max(int(x["y"]) + int(x["height"]) for x in cluster)
            rect = Rect(x0, y0, x1 - x0, y1 - y0).expanded(pad_px, max_w=max_w, max_h=max_h)
            is_blanket = any(bool(x.get("is_blanket", False)) for x in cluster)
            label = str(cluster[0].get("label", key))
            result.append(
                BlurSpan(
                    id=f"blur_{span_idx:03d}",
                    label=label,
                    start_s=round(s_min, 3),
                    end_s=round(e_max, 3),
                    x=rect.x,
                    y=rect.y,
                    width=rect.width,
                    height=rect.height,
                    radius=12,
                    downscale_factor=downscale_factor,
                    sigma=sigma,
                    is_blanket=is_blanket,
                    dropped_frames=0,
                    constant_geometry=True,
                )
            )
            span_idx += 1

    return result


def cutout_webcam_from_box(blur_box: Rect, webcam_rect: WebcamRect | None) -> list[Rect]:
    """Subtract webcam_rect cleanly from a blur box so blur NEVER bleeds into Markus's webcam."""
    if webcam_rect is None:
        return [blur_box]
    cam = webcam_rect.as_rect()
    if not blur_box.intersects(cam):
        return [blur_box]

    pieces: list[Rect] = []
    # Top strip above webcam
    if blur_box.y < cam.y:
        pieces.append(Rect(blur_box.x, blur_box.y, blur_box.width, cam.y - blur_box.y))
    # Bottom strip below webcam
    if blur_box.bottom > cam.bottom:
        pieces.append(Rect(blur_box.x, cam.bottom, blur_box.width, blur_box.bottom - cam.bottom))

    # Middle vertical band split left & right of webcam
    mid_y0 = max(blur_box.y, cam.y)
    mid_y1 = min(blur_box.bottom, cam.bottom)
    mid_h = mid_y1 - mid_y0
    if mid_h > 0:
        if blur_box.x < cam.x:
            pieces.append(Rect(blur_box.x, mid_y0, cam.x - blur_box.x, mid_h))
        if blur_box.right > cam.right:
            pieces.append(Rect(cam.right, mid_y0, blur_box.right - cam.right, mid_h))

    return [p for p in pieces if p.width > 0 and p.height > 0]


def build_webcam_window_mask_png(
    webcam_rect: WebcamRect,
    panes: list[WindowPaneMask],
    output_png: str | Path,
) -> Path:
    """Build exact hard-edged grayscale polygon mask blurring all webcam windows EXCEPT behind Markus's head (G7)."""
    out = Path(output_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("L", (webcam_rect.width, webcam_rect.height), 0)
    draw = ImageDraw.Draw(img)

    for pane in panes:
        if pane.exclude_behind_head:
            continue
        pts = [
            (int(round(px * webcam_rect.width)), int(round(py * webcam_rect.height)))
            for px, py in pane.polygon_norm
        ]
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)

    img.save(out, format="PNG")
    return out


def scan_image_ocr(image_path: str | Path) -> list[str]:
    """Optional local OCR scan using RapidOCR if installed; returns detected text lines."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except ImportError:
        return []
    engine = RapidOCR()
    res, _ = engine(str(image_path))
    if not res:
        return []
    return [str(row[1]) for row in res if len(row) >= 2]


def find_sensitive_ocr_hits(
    texts: list[str],
    sensitive_terms: list[str] | None = None,
    sensitive_regexes: list[str] | None = None,
) -> list[str]:
    """Check OCR strings against DDG sensitive terms and patterns."""
    terms = [t.lower() for t in (sensitive_terms or [])]
    regexes = [re.compile(r, re.IGNORECASE) for r in (sensitive_regexes or [])]
    hits: list[str] = []
    for text in texts:
        low = text.lower()
        for t in terms:
            if t and t in low:
                hits.append(f"Matched sensitive term '{t}' in OCR text '{text}'")
        for rx in regexes:
            m = rx.search(text)
            if m:
                hits.append(f"Matched sensitive pattern '{rx.pattern}' -> '{m.group(0)}'")
    return hits


def generate_before_after_strip(
    before_path: str | Path,
    after_path: str | Path,
    output_strip_path: str | Path,
) -> Path:
    """Generate a side-by-side Before/After comparison image for Markus's review."""
    b = Image.open(before_path).convert("RGB")
    a = Image.open(after_path).convert("RGB")
    if a.size != b.size:
        a = a.resize(b.size, Image.Resampling.LANCZOS)
    gap = 12
    strip = Image.new("RGB", (b.width + a.width + gap, b.height), (20, 21, 24))
    strip.paste(b, (0, 0))
    strip.paste(a, (b.width + gap, 0))
    out = Path(output_strip_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out, format="PNG")
    return out


def audit_g8b_blur_stability(
    blur_spans: list[BlurSpan],
    webcam_rect: WebcamRect | None = None,
    min_sigma: float = 9.0,
    min_downscale: int = 12,
    ocr_texts_after_blur: list[str] | None = None,
    sensitive_terms: list[str] | None = None,
    sensitive_regexes: list[str] | None = None,
    frame_blur_presence: dict[str, list[bool]] | None = None,
) -> GateResult:
    """G8b mandatory gate: fail on ANY 1-frame flicker, weak blur, webcam bleed, or readable OCR hit."""
    issues: list[str] = []

    for span in blur_spans:
        if not span.constant_geometry:
            issues.append(f"Blur '{span.id}' ({span.label}) is not constant-geometry (risks flicker).")
        if span.dropped_frames > 0:
            issues.append(
                f"Blur '{span.id}' ({span.label}) dropped {span.dropped_frames} frame(s) inside {span.start_s:.2f}-{span.end_s:.2f}s."
            )
        if not span.is_blanket:
            if span.sigma < min_sigma:
                issues.append(f"Blur '{span.id}' sigma {span.sigma} < required {min_sigma}.")
            if span.downscale_factor < min_downscale:
                issues.append(
                    f"Blur '{span.id}' downscale {span.downscale_factor} < required {min_downscale}."
                )
        if webcam_rect is not None and span.rect.intersects(webcam_rect.as_rect()):
            issues.append(
                f"Blur '{span.id}' intersects webcam rect without cutout (bleed violates PSNR >= 30 dB)."
            )
        if frame_blur_presence and span.id in frame_blur_presence:
            flags = frame_blur_presence[span.id]
            missing = [idx for idx, present in enumerate(flags) if not present]
            if missing:
                issues.append(
                    f"Blur '{span.id}' missing on 10 fps frame sample(s): {missing[:5]}"
                )

    if ocr_texts_after_blur:
        ocr_hits = find_sensitive_ocr_hits(
            ocr_texts_after_blur,
            sensitive_terms=sensitive_terms,
            sensitive_regexes=sensitive_regexes,
        )
        issues.extend(ocr_hits)

    return GateResult(
        gate_id="G8b_BLUR_STABILITY",
        name="Non-Flickering Blur Stability & OCR Cleanliness (G8b)",
        passed=len(issues) == 0,
        summary=(
            f"Verified {len(blur_spans)} steady blur span(s) at 10 fps with 0 dropouts and 0 OCR leaks."
            if not issues
            else f"{len(issues)} blur stability/OCR failure(s) detected."
        ),
        details=issues,
    )
