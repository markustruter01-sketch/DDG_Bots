"""12-column Night Glass snap grid, face clearance, overlay area cap (75%), and alignment gates (G4/G5)."""

from __future__ import annotations

from typing import Any

from .models import GateResult, OverlayItem, Rect


GRID_WIDTH = 1920
GRID_HEIGHT = 1080
GRID_MARGIN = 20
GRID_GUTTER = 16
GRID_COLS = 12
GRID_BASELINE = 8
TOP_BAR_Y0 = 20
TOP_BAR_Y1 = 92
CONTENT_Y0 = 112
COL_WIDTH = (GRID_WIDTH - 2 * GRID_MARGIN - (GRID_COLS - 1) * GRID_GUTTER) // GRID_COLS  # 142 px


def col_x0(col_idx: int) -> int:
    c = max(0, min(GRID_COLS - 1, col_idx))
    return GRID_MARGIN + c * (COL_WIDTH + GRID_GUTTER)


def col_x1(col_idx: int) -> int:
    return col_x0(col_idx) + COL_WIDTH


def span_width(num_cols: int) -> int:
    n = max(1, min(GRID_COLS, num_cols))
    return n * COL_WIDTH + (n - 1) * GRID_GUTTER


def snap_rect_to_grid(rect: Rect, anchor: str = "right") -> Rect:
    """Snap panel rect to 12-col grid & 8 px vertical baseline starting at y >= 112."""
    all_x0 = [col_x0(i) for i in range(GRID_COLS)]
    all_x1 = [col_x1(i) for i in range(GRID_COLS)]

    if anchor == "left":
        snapped_x = min(all_x0, key=lambda gx: abs(gx - rect.x))
        # Also snap width to nearest multi-column span
        best_w = min(
            (span_width(k) for k in range(1, GRID_COLS + 1)),
            key=lambda w: abs(w - rect.width),
        )
        if snapped_x + best_w > GRID_WIDTH - GRID_MARGIN:
            best_w = (GRID_WIDTH - GRID_MARGIN) - snapped_x
    else:
        # Right-anchored: snap right edge to nearest column end (1900 flush with tab bar)
        snapped_right = min(all_x1, key=lambda gx: abs(gx - rect.right))
        best_w = min(
            (span_width(k) for k in range(1, GRID_COLS + 1)),
            key=lambda w: abs(w - rect.width),
        )
        snapped_x = max(GRID_MARGIN, snapped_right - best_w)

    snapped_y = max(CONTENT_Y0, int(round(rect.y / GRID_BASELINE) * GRID_BASELINE))
    snapped_h = max(GRID_BASELINE * 4, int(round(rect.height / GRID_BASELINE) * GRID_BASELINE))
    if snapped_y + snapped_h > GRID_HEIGHT - GRID_MARGIN:
        snapped_h = max(GRID_BASELINE * 4, (GRID_HEIGHT - GRID_MARGIN) - snapped_y)

    return Rect(x=snapped_x, y=snapped_y, width=best_w, height=snapped_h)


def align_check(overlays: list[OverlayItem], tol_px: int = 1) -> GateResult:
    """Verify HUD & business tab bar alignment (y=20..92) and panel grid alignment <= 1 px (G4)."""
    issues: list[str] = []
    valid_x0 = [col_x0(i) for i in range(GRID_COLS)]
    valid_x1 = [col_x1(i) for i in range(GRID_COLS)]

    hud_items = [o for o in overlays if o.kind == "hud"]
    tab_items = [o for o in overlays if o.kind == "tab_bar"]

    if hud_items and tab_items:
        h = hud_items[0]
        t = tab_items[0]
        if abs(h.y - TOP_BAR_Y0) > tol_px or abs(t.y - TOP_BAR_Y0) > tol_px:
            issues.append(f"Top bars y ({h.y}, {t.y}) must match y={TOP_BAR_Y0} within {tol_px}px.")
        if abs(h.height - t.height) > tol_px or abs((h.y + h.height) - TOP_BAR_Y1) > tol_px:
            issues.append(
                f"HUD height ({h.height}) and tab bar height ({t.height}) must match y={TOP_BAR_Y0}..{TOP_BAR_Y1} within {tol_px}px."
            )
        if abs(h.x - GRID_MARGIN) > tol_px:
            issues.append(f"HUD x0 ({h.x}) must equal margin {GRID_MARGIN} within {tol_px}px.")
        if abs(t.rect.right - (GRID_WIDTH - GRID_MARGIN)) > tol_px:
            issues.append(f"Tab bar x1 ({t.rect.right}) must equal {GRID_WIDTH - GRID_MARGIN} within {tol_px}px.")

    for o in overlays:
        if o.is_grid_exempt or o.kind in ("hud", "tab_bar", "bubble", "freya_tag", "subtitle"):
            continue
        x0_ok = any(abs(o.x - gx) <= tol_px for gx in valid_x0)
        x1_ok = any(abs(o.rect.right - gx) <= tol_px for gx in valid_x1)
        if not (x0_ok or x1_ok):
            issues.append(
                f"Overlay '{o.id}' ({o.x}..{o.rect.right}) is not snapped to any 12-col grid edge."
            )
        if o.y < CONTENT_Y0 - tol_px:
            issues.append(
                f"Overlay '{o.id}' y={o.y} intrudes into top HUD/tab gutter (must be y >= {CONTENT_Y0})."
            )
        if (o.y % GRID_BASELINE) > tol_px and (GRID_BASELINE - (o.y % GRID_BASELINE)) > tol_px:
            issues.append(f"Overlay '{o.id}' y={o.y} is off {GRID_BASELINE}px baseline.")

    return GateResult(
        gate_id="G4_GRID_ALIGN",
        name="12-Column Snap Grid & Top Bar Alignment (G4)",
        passed=len(issues) == 0,
        summary=(
            "All panels snapped cleanly to 12-col grid and top bars match within 1 px."
            if not issues
            else f"{len(issues)} alignment error(s) found."
        ),
        details=issues,
    )


def face_clearance_check(
    overlays: list[OverlayItem],
    face_box: Rect | None,
    min_margin_ratio: float = 0.15,
    frame_w: int = GRID_WIDTH,
    frame_h: int = GRID_HEIGHT,
) -> list[str]:
    """Ensure NO overlay covers or sits within 15% frame width of Markus's face box (G5)."""
    if face_box is None:
        return []
    margin_px = int(round(frame_w * min_margin_ratio))
    safe_zone = face_box.expanded(margin_px, max_w=frame_w, max_h=frame_h)
    issues: list[str] = []
    for o in overlays:
        if o.is_cue_exempt:
            continue
        if o.rect.intersects(safe_zone):
            issues.append(
                f"Overlay '{o.id}' ({o.x},{o.y},{o.width}x{o.height}) violates "
                f"{margin_px}px face clearance around {face_box.to_dict()}."
            )
    return issues


def overlap_and_area_check(
    overlays: list[OverlayItem],
    area_cap: float = 0.75,
    frame_w: int = GRID_WIDTH,
    frame_h: int = GRID_HEIGHT,
) -> tuple[list[str], float]:
    """Check zero space-time overlap and <= 75% combined simultaneous overlay footprint (G5)."""
    counted = [o for o in overlays if o.kind != "subtitle" and not o.extra.get("is_small_watermark", False)]
    if not counted:
        return [], 0.0

    time_points = sorted({o.start_s for o in counted} | {o.end_s for o in counted})
    frame_area = float(frame_w * frame_h)
    issues: list[str] = []
    peak_ratio = 0.0
    reported_pairs: set[tuple[str, str]] = set()

    for t0, t1 in zip(time_points, time_points[1:]):
        if t1 - t0 < 1e-4:
            continue
        t_mid = (t0 + t1) / 2.0
        active = [o for o in counted if o.start_s <= t_mid < o.end_s]
        if not active:
            continue

        # Check pairwise intersections
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                a, b = active[i], active[j]
                if a.rect.intersects(b.rect):
                    pair = (min(a.id, b.id), max(a.id, b.id))
                    if pair not in reported_pairs:
                        reported_pairs.add(pair)
                        issues.append(
                            f"Overlapping overlays '{a.id}' (prio {a.priority}) and '{b.id}' (prio {b.priority}) "
                            f"around {t_mid:.2f}s."
                        )

        total_area = sum(o.rect.area for o in active)
        ratio = total_area / frame_area
        if ratio > peak_ratio:
            peak_ratio = ratio
        if ratio > area_cap:
            issues.append(
                f"Combined overlay area {ratio*100:.1f}% exceeds {area_cap*100:.0f}% cap at {t_mid:.2f}s."
            )

    return issues, round(peak_ratio, 4)


def duration_and_wild_cap_check(
    overlays: list[OverlayItem],
    mode: str = "longform",
    max_wild_ratio: float = 0.25,
) -> list[str]:
    """Enforce per-type minimum durations and <= 25% wild animation cap (G5)."""
    issues: list[str] = []
    non_persistent = [o for o in overlays if not o.is_persistent and o.kind not in ("hud", "tab_bar", "agenda")]

    for o in non_persistent:
        if mode == "short":
            if o.kind in ("quick_chip", "bubble") and o.duration < 1.2:
                issues.append(f"Short overlay '{o.id}' duration {o.duration:.2f}s < 1.2s.")
        elif mode == "deepdive":
            if o.kind == "heavy_card" and o.duration < 15.0:
                issues.append(f"Heavy card '{o.id}' duration {o.duration:.2f}s < 15.0s.")
            elif o.kind in ("deep_graphic", "bubble") and o.duration < 10.0:
                issues.append(f"Deep-dive graphic '{o.id}' duration {o.duration:.2f}s < 10.0s.")
            elif o.kind in ("quick_chip", "mention_card") and o.duration < 4.5:
                issues.append(f"Overlay '{o.id}' duration {o.duration:.2f}s < 4.5s.")
        else:  # longform
            if o.kind == "heavy_card" and o.duration < 15.0:
                issues.append(f"Heavy card '{o.id}' duration {o.duration:.2f}s < 15.0s.")
            elif o.kind in ("quick_chip", "mention_card", "deep_graphic", "bubble") and o.duration < 4.5:
                issues.append(f"Longform pop-up '{o.id}' duration {o.duration:.2f}s < 4.5s.")

    anim_pool = [o for o in non_persistent if not o.is_cue_exempt]
    if anim_pool:
        wild_count = sum(1 for o in anim_pool if o.is_wild)
        ratio = wild_count / len(anim_pool)
        if ratio > max_wild_ratio:
            issues.append(
                f"Wild animation ratio {ratio*100:.1f}% ({wild_count}/{len(anim_pool)}) exceeds {max_wild_ratio*100:.0f}% cap."
            )

    return issues
