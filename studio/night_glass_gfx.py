"""DDG Night Glass v5 Pillow graphics generator, HUD equation renderer (G0), text-fit auditor (G4), and ASS subtitles (G3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .audio_engine import mask_swear_word
from .models import HudNumbers, Rect, STUDIO_ROOT, Transcript, load_brand


# Unicode emoji ranges forbidden across all Night Glass graphics and captions (G9)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def contains_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def is_red_number_color(rgb: tuple[int, int, int]) -> bool:
    """Detect forbidden red numbers (never red for numbers or negatives; orange #FF9F43 is required)."""
    r, g, b = rgb[:3]
    return r >= 200 and g <= 115 and b <= 115


def load_font(size: int, mono: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    brand = load_brand()
    fonts_dir = STUDIO_ROOT / "assets" / "fonts"
    candidates: list[Path] = []
    pref = brand.get("fonts", {}).get("preferred_files", {})
    if mono:
        candidates.append(fonts_dir / pref.get("mono_medium" if bold else "mono", "GeistMono-Regular.ttf"))
        candidates.extend([Path("C:/Windows/Fonts/consolab.ttf"), Path("C:/Windows/Fonts/consola.ttf")])
    else:
        key = "semibold" if bold else "regular"
        candidates.append(fonts_dir / pref.get(key, "Geist-Regular.ttf"))
        candidates.extend([
            Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        ])

    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def fit_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start_size: int = 38,
    min_size: int = 30,
    max_lines: int = 2,
    bold: bool = True,
) -> tuple[list[str], int, ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """Auto-shrink title down to 30 px, then wrap cleanly to max_lines without clipping."""
    for sz in range(start_size, min_size - 1, -2):
        font = load_font(sz, mono=False, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return [text], sz, font, True

    font = load_font(min_size, mono=False, bold=bold)
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        bbox = draw.textbbox((0, 0), cand, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    all_fit = len(lines) <= max_lines and all(
        (draw.textbbox((0, 0), ln, font=font)[2] - draw.textbbox((0, 0), ln, font=font)[0]) <= max_width
        for ln in lines
    )
    return lines[:max_lines], min_size, font, all_fit


def text_fit_check(
    text_boxes: list[tuple[str, tuple[int, int, int, int]]],
    panel_width: int,
    panel_height: int,
    padding: int = 12,
) -> tuple[bool, list[str]]:
    """Verify every text element sits cleanly inside panel padding with zero overlapping lines."""
    issues: list[str] = []
    for label, (x0, y0, x1, y1) in text_boxes:
        if x0 < padding or y0 < padding or x1 > (panel_width - padding) or y1 > (panel_height - padding):
            issues.append(
                f"Text '{label}' box {(x0, y0, x1, y1)} clips panel {panel_width}x{panel_height} (pad {padding})."
            )
    for i in range(len(text_boxes)):
        for j in range(i + 1, len(text_boxes)):
            la, (ax0, ay0, ax1, ay1) = text_boxes[i]
            lb, (bx0, by0, bx1, by1) = text_boxes[j]
            if not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0):
                issues.append(f"Text boxes overlap: '{la}' and '{lb}'.")
    return len(issues) == 0, issues


def _draw_frosted_base(width: int, height: int, accent_hex: str = "#6cc7f0", radius: int = 16) -> Image.Image:
    """Create Night Glass v6.1 rounded frosted panel with hairline border, top highlight, and single 2 px accent line."""
    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    # Dark frosted glass fill + 1 px hairline border
    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)],
        radius=radius,
        fill=(16, 18, 24, 212),
        outline=(255, 255, 255, 28),
        width=1,
    )
    # Subtle top highlight
    draw.line([(radius, 1), (width - radius, 1)], fill=(255, 255, 255, 18), width=1)
    # Single 2 px accent line along top-left card header
    ar, ag, ab = _hex_to_rgb(accent_hex)
    draw.line([(radius, 2), (min(width - radius, radius + 76), 2)], fill=(ar, ag, ab, 255), width=2)
    return panel


def _wrap_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Word-wrap lines cleanly to max_width so body and footer text never clip panel bounds."""
    wrapped: list[str] = []
    for raw in lines:
        if not raw:
            continue
        words = raw.split()
        cur = ""
        for w in words:
            cand = f"{cur} {w}".strip()
            bbox = draw.textbbox((0, 0), cand, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                cur = cand
            else:
                if cur:
                    wrapped.append(cur)
                cur = w
        if cur:
            wrapped.append(cur)
    return wrapped


def render_glass_panel(
    *,
    title: str,
    body_lines: list[str],
    output_png: str | Path,
    kicker: str = "",
    footer: str = "",
    width: int = 460,
    min_height: int = 140,
    accent_hex: str = "#6cc7f0",
) -> tuple[Path, dict[str, Any]]:
    """Render a Night Glass v5 card with dynamic height, separate RGBA text layer, and text-fit validation."""
    for s in [kicker, title, *body_lines, footer]:
        if contains_emoji(s):
            raise ValueError(f"G9 violation: emoji forbidden in Night Glass graphics ('{s}').")

    pad = 18
    max_inner_w = width - 2 * pad
    tmp_img = Image.new("RGBA", (width, 10), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp_img)

    title_lines, title_sz, title_font, title_fits = fit_title(
        tmp_draw, title, max_width=max_inner_w, start_size=34, min_size=30, max_lines=2
    )
    kicker_font = load_font(12, mono=True, bold=True)
    body_font = load_font(16, mono=False, bold=False)
    footer_font = load_font(12, mono=True, bold=False)

    wrapped_body = _wrap_lines(tmp_draw, body_lines, body_font, max_inner_w)
    wrapped_footer = _wrap_lines(tmp_draw, [footer], footer_font, max_inner_w) if footer else []

    # Calculate exact dynamic height using measured line boxes
    y_cursor = pad + 4
    if kicker:
        kb = tmp_draw.textbbox((0, 0), kicker.upper(), font=kicker_font)
        y_cursor += (kb[3] - kb[1]) + 8
    for tline in title_lines:
        tb = tmp_draw.textbbox((0, 0), tline, font=title_font)
        y_cursor += (tb[3] - tb[1]) + 6
    y_cursor += 4
    for bline in wrapped_body:
        bb = tmp_draw.textbbox((0, 0), bline, font=body_font)
        y_cursor += max(22, (bb[3] - bb[1]) + 6)
    if wrapped_footer:
        y_cursor += 6
        for fline in wrapped_footer:
            fb = tmp_draw.textbbox((0, 0), fline, font=footer_font)
            y_cursor += max(18, (fb[3] - fb[1]) + 4)
    height = max(min_height, y_cursor + pad)

    panel = _draw_frosted_base(width, height, accent_hex=accent_hex, radius=16)
    # Separate RGBA text layer so translucent alpha never punches holes in glass
    txt_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt_layer)

    boxes: list[tuple[str, tuple[int, int, int, int]]] = []
    y = pad + 4
    if kicker:
        k_txt = kicker.upper()
        kb = td.textbbox((pad, y), k_txt, font=kicker_font)
        td.text((pad, y), k_txt, font=kicker_font, fill=(255, 255, 255, 165))
        boxes.append(("kicker", kb))
        y += (kb[3] - kb[1]) + 8

    for idx, tline in enumerate(title_lines):
        tb = td.textbbox((pad, y), tline, font=title_font)
        td.text((pad, y), tline, font=title_font, fill=(255, 255, 255, 255))
        boxes.append((f"title_{idx}", tb))
        y += (tb[3] - tb[1]) + 6

    y += 4
    for idx, bline in enumerate(wrapped_body):
        bb = td.textbbox((pad, y), bline, font=body_font)
        td.text((pad, y), bline, font=body_font, fill=(255, 255, 255, 200))
        boxes.append((f"body_{idx}", bb))
        y += max(22, (bb[3] - bb[1]) + 6)

    if wrapped_footer:
        y += 6
        for idx, fline in enumerate(wrapped_footer):
            fb = td.textbbox((pad, y), fline, font=footer_font)
            td.text((pad, y), fline, font=footer_font, fill=(255, 255, 255, 158))
            boxes.append((f"footer_{idx}", fb))
            y += max(18, (fb[3] - fb[1]) + 4)

    ok, fit_issues = text_fit_check(boxes, width, height, padding=12)
    final_img = Image.alpha_composite(panel, txt_layer)
    out = Path(output_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    final_img.save(out, format="PNG")

    return out, {
        "width": width,
        "height": height,
        "title_size": title_sz,
        "title_fits": title_fits,
        "text_fit_ok": ok and title_fits,
        "issues": fit_issues,
    }


def _fmt_int(val: int | None) -> str:
    if val is None:
        return "—"
    return f"{val:,}"


def _fmt_money(val: float | None) -> str:
    if val is None:
        return "—"
    if val < 0:
        return f"-${abs(val):,.2f}"
    return f"${val:,.2f}"


def render_hud_bar(
    hud: HudNumbers,
    output_png: str | Path,
    width: int = 1340,
    height: int = 72,
) -> tuple[Path, dict[str, Any]]:
    """Render top-left Night Glass HUD equation bar (y=20..92, height=72 px) with exact G0 math check."""
    balanced, balance_msg = hud.is_balanced()
    panel = _draw_frosted_base(width, height, accent_hex="#6cc7f0", radius=16)
    txt = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)

    val_font = load_font(20, mono=True, bold=True)
    lbl_font = load_font(10, mono=True, bold=False)

    orange = (255, 159, 67, 255)   # #FF9F43
    green = (61, 220, 151, 255)    # #3DDC97
    yellow = (255, 214, 92, 255)   # #FFD65C
    pink = (255, 126, 182, 255)    # #FF7EB6
    white = (255, 255, 255, 255)
    muted = (255, 255, 255, 158)

    # Verify zero forbidden red numbers
    for c in (orange, green, yellow, pink):
        if is_red_number_color(c[:3]):
            raise ValueError("G0 violation: red number color detected in HUD.")

    tiles = [
        ("FOLLOWERS", _fmt_int(hud.followers), white, None),
        ("VIEWS", _fmt_int(hud.views), white, None),
        ("LIKES", _fmt_int(hud.likes), white, "|"),
        ("EXPENSES", _fmt_money(hud.expenses), orange, "-"),
        ("GROSS REV", _fmt_money(hud.gross_revenue), green, "="),
        ("DEBT", _fmt_money(hud.debt), yellow, "|"),
        ("CHARITY", _fmt_money(hud.charity_deducted), pink, "->"),
        ("NET PROFIT", _fmt_money(hud.net_profit), orange, None),
    ]

    x = 22
    slot_w = (width - 44) // len(tiles)
    boxes: list[tuple[str, tuple[int, int, int, int]]] = []
    for idx, (label, val_str, col, op) in enumerate(tiles):
        vb = td.textbbox((x, 14), val_str, font=val_font)
        td.text((x, 14), val_str, font=val_font, fill=col)
        lb = td.textbbox((x, 44), label, font=lbl_font)
        td.text((x, 44), label, font=lbl_font, fill=muted)
        boxes.append((f"val_{idx}", vb))
        boxes.append((f"lbl_{idx}", lb))
        if op:
            op_x = x + slot_w - 22
            td.text((op_x, 18), op, font=lbl_font, fill=(255, 255, 255, 120))
        x += slot_w

    fit_ok, issues = text_fit_check(boxes, width, height, padding=8)
    out = Path(output_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(panel, txt).save(out, format="PNG")
    return out, {
        "balanced": balanced,
        "balance_msg": balance_msg,
        "width": width,
        "height": height,
        "text_fit_ok": fit_ok,
        "issues": issues,
    }


def render_business_tab_bar(
    active_business: str,
    output_png: str | Path,
    width: int = 524,
    height: int = 72,
) -> Path:
    """Render top-right business tab bar matching HUD height (72 px) within <= 1 px (Night Glass v6.1, G4)."""
    # v6.1 p. 7: DDG business cards use Ice (#6cc7f0), Mint (#3ddc97), Violet (#a78bfa) and White; amber is ONLY for problems.
    tabs = [
        ("DDG", "#6cc7f0"),
        ("Finance", "#3ddc97"),
        ("Coffee", "#ffffff"),
        ("Fitness", "#ffffff"),
        ("Creative", "#a78bfa"),
    ]
    active_accent = next((hex_c for name, hex_c in tabs if name.lower() == active_business.lower()), "#6cc7f0")
    panel = _draw_frosted_base(width, height, accent_hex=active_accent, radius=16)
    txt = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    font = load_font(14, mono=False, bold=True)

    pill_w = (width - 28) // len(tabs)
    x = 14
    for name, hex_c in tabs:
        is_active = name.lower() == active_business.lower()
        if is_active:
            td.rounded_rectangle([(x + 2, 16), (x + pill_w - 4, height - 16)], radius=12, fill=(255, 255, 255, 26))
            ar, ag, ab = _hex_to_rgb(hex_c)
            td.line([(x + 12, height - 17), (x + pill_w - 14, height - 17)], fill=(ar, ag, ab, 255), width=2)
        td.text((x + 16, 26), name, font=font, fill=(255, 255, 255, 255 if is_active else 160))
        x += pill_w

    out = Path(output_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(panel, txt).save(out, format="PNG")
    return out


def render_factcheck_card(
    index_num: int,
    said_text: str,
    actual_text: str,
    source_label: str,
    output_png: str | Path,
    width: int = 460,
) -> tuple[Path, dict[str, Any]]:
    """Render Night Glass 'FACT CHECK #n' card with 'MARKUS WRONG [n]' and permission footer."""
    return render_glass_panel(
        kicker=f"FACT CHECK #{index_num}  |  MARKUS WRONG [{index_num}]",
        title="Correction",
        body_lines=[
            f"SAID: {said_text}",
            f"ACTUAL: {actual_text}",
            f"SOURCE: {source_label}",
        ],
        footer="Markus gave Freya permission to correct him after the fact",
        output_png=output_png,
        width=width,
        accent_hex="#6cc7f0",
    )


def render_agenda_widget(
    items: list[str],
    current_index: int,
    output_png: str | Path,
    window_size: int = 6,
    side_quest: str | None = None,
    width: int = 380,
) -> tuple[Path, dict[str, Any]]:
    """Render compact 5-7 item scrolling Agenda list in fixed master order + optional playful Side-Quest badge."""
    total = len(items)
    start = max(0, min(max(0, total - window_size), current_index - window_size // 2))
    visible = items[start : start + window_size]

    lines: list[str] = []
    for offset, item in enumerate(visible):
        real_idx = start + offset
        if real_idx < current_index:
            lines.append(f"[done] {item}")
        elif real_idx == current_index:
            lines.append(f">> {item}")
        else:
            lines.append(f"   {item}")

    footer = ""
    if side_quest:
        back_to = items[current_index] if 0 <= current_index < total else ""
        footer = f"SIDE QUEST: {side_quest} (back to: {back_to})"

    return render_glass_panel(
        kicker="EPISODE AGENDA",
        title="Topics",
        body_lines=lines,
        footer=footer,
        output_png=output_png,
        width=width,
        accent_hex="#6cc7f0",
    )


def _format_ass_time(seconds: float) -> str:
    s = max(0.0, seconds)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    cs = int(round((s % 1.0) * 100))
    if cs >= 100:
        sec += 1
        cs = 0
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def generate_ass_subtitles(
    transcript: Transcript,
    output_ass: str | Path,
    swear_spans: list[dict[str, Any]] | None = None,
    is_short: bool = False,
    face_box: Rect | None = None,
) -> Path:
    """Generate Night Glass ASS subtitles masking swears (f***/s***), zero emojis, and clearing face + avatar (G3)."""
    words = sorted(transcript.words, key=lambda w: w.start)
    swear_spans = swear_spans or []

    if is_short:
        play_x, play_y = 1080, 1920
        # Place captions in top/mid empty space, NEVER covering face and out of bottom 20% & right edge
        if face_box and face_box.y > 700:
            alignment = 8  # top-center
            margin_v = 260
        else:
            alignment = 5  # mid-center
            margin_v = 80
        margin_l, margin_r = 60, 140
        font_size = 54
        chunk_size = 3
    else:
        play_x, play_y = 1920, 1080
        alignment = 2  # bottom-center inside [MarginL..1920-MarginR]
        margin_l = 780
        margin_r = 330  # right edge <= 1590, clears avatar bottom-right
        margin_v = 48
        font_size = 44
        chunk_size = 7

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_x}
PlayResY: {play_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: NightGlass,Geist,{font_size},&H00FFFFFF,&H00F0C76C,&H00181514,&H85181210,1,0,0,0,100,100,0,0,3,6,0,{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    for i in range(0, len(words), chunk_size):
        chunk = words[i : i + chunk_size]
        if not chunk:
            continue
        t_start = _format_ass_time(chunk[0].start)
        t_end = _format_ass_time(max(chunk[-1].end, chunk[0].start + 0.25))
        rendered_words: list[str] = []
        for w in chunk:
            is_swear = any(
                not (w.end <= float(sp["start_s"]) or float(sp["end_s"]) <= w.start)
                for sp in swear_spans
            )
            txt = mask_swear_word(w.word) if is_swear else w.word
            txt = _EMOJI_RE.sub("", txt).strip()
            if txt:
                rendered_words.append(txt)
        line_text = " ".join(rendered_words).replace("{", "(").replace("}", ")")
        if line_text:
            events.append(f"Dialogue: 0,{t_start},{t_end},NightGlass,,0,0,0,,{line_text}")

    out = Path(output_ass)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out
