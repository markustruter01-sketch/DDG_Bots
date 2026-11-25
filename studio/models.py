"""Core data models, config loaders, and filesystem path-jail enforcement."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

AEST_TZ = timezone(timedelta(hours=10))
STUDIO_ROOT = Path(__file__).resolve().parent.parent


class SecurityError(PermissionError):
    """Raised when an operation violates DDG path-jail or security boundaries."""


def now_aest_iso() -> str:
    return datetime.now(AEST_TZ).isoformat(timespec="seconds")


def load_json(path: str | Path) -> dict[str, Any]:
    with open(Path(path), "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str | Path, data: Any, allowed_roots: list[str | Path] | None = None) -> Path:
    target = Path(path)
    if allowed_roots is not None:
        assert_in_allowed_roots(target, allowed_roots)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return target


def load_settings(studio_root: str | Path = STUDIO_ROOT) -> dict[str, Any]:
    return load_json(Path(studio_root) / "config" / "settings.json")


def load_rules(studio_root: str | Path = STUDIO_ROOT) -> dict[str, Any]:
    return load_json(Path(studio_root) / "config" / "rules.json")


def load_brand(studio_root: str | Path = STUDIO_ROOT) -> dict[str, Any]:
    return load_json(Path(studio_root) / "config" / "brand_night_glass.json")


def _norm_case_path(p: str | Path) -> str:
    resolved = str(Path(p).resolve())
    return os.path.normcase(os.path.normpath(resolved))


def assert_in_allowed_roots(
    path: str | Path,
    allowed_roots: list[str | Path] | None = None,
) -> Path:
    """Ensure path resolves strictly inside allowed DDG studio/footage roots."""
    if allowed_roots is None:
        settings = load_settings()
        allowed_roots = settings.get("allowed_roots", [str(STUDIO_ROOT)])

    target_resolved = Path(path).resolve()
    target_norm = _norm_case_path(target_resolved)

    for root in allowed_roots:
        root_norm = _norm_case_path(root)
        if target_norm == root_norm or target_norm.startswith(root_norm + os.sep):
            return target_resolved

    raise SecurityError(
        f"Blocked access outside allowed studio/footage roots: {target_resolved}"
    )


@dataclass
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )

    def expanded(self, pad_px: int, max_w: int = 1920, max_h: int = 1080) -> "Rect":
        x0 = max(0, self.x - pad_px)
        y0 = max(0, self.y - pad_px)
        x1 = min(max_w, self.right + pad_px)
        y1 = min(max_h, self.bottom + pad_px)
        return Rect(x=x0, y=y0, width=max(0, x1 - x0), height=max(0, y1 - y0))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rect":
        return cls(**data)


@dataclass
class WordTimestamp:
    word: str
    start: float
    end: float
    confidence: float = 1.0
    speaker: str = "Markus"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WordTimestamp":
        return cls(**data)


@dataclass
class Transcript:
    source_path: str
    language: str = "en"
    words: list[WordTimestamp] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)

    def full_text(self) -> str:
        if self.words:
            return " ".join(w.word for w in self.words)
        return " ".join(str(s.get("text", "")).strip() for s in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "language": self.language,
            "words": [w.to_dict() for w in self.words],
            "segments": self.segments,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        return cls(
            source_path=data.get("source_path", ""),
            language=data.get("language", "en"),
            words=[WordTimestamp.from_dict(w) for w in data.get("words", [])],
            segments=list(data.get("segments", [])),
        )


@dataclass
class HudNumbers:
    followers: int | None
    views: int | None
    likes: int | None
    expenses: float | None
    gross_revenue: float | None
    debt: float | None
    charity_deducted: float | None
    net_profit: float | None
    source_label: str = "DDG Control"
    source_url: str = ""
    checked_at_aest: str = ""

    def is_balanced(self, tolerance: float = 0.01) -> tuple[bool, str]:
        if None in (self.expenses, self.gross_revenue, self.debt, self.charity_deducted, self.net_profit):
            return True, "Missing fields represented as unknown ('—')"
        # Control v3.2 equation: expenses - gross_revenue = debt | charity_deducted -> net_profit
        # Accept either signed debt = expenses - gross_revenue AND net_profit = gross_revenue - expenses - charity_deducted
        # or Control's positive-magnitude variant net_profit = gross_revenue - expenses - charity_deducted
        expected_debt = round(float(self.expenses) - float(self.gross_revenue), 2)
        actual_debt = round(float(self.debt), 2)
        if abs(expected_debt - actual_debt) > tolerance:
            return False, (
                f"HUD debt mismatch: expenses({self.expenses:.2f}) - gross_revenue({self.gross_revenue:.2f}) "
                f"= {expected_debt:.2f}, got debt={actual_debt:.2f}"
            )
        expected_net = round(float(self.gross_revenue) - float(self.expenses) - float(self.charity_deducted), 2)
        expected_net_alt = round(float(self.gross_revenue) - float(self.expenses) + float(self.charity_deducted), 2)
        actual_net = round(float(self.net_profit), 2)
        if abs(expected_net - actual_net) > tolerance and abs(expected_net_alt - actual_net) > tolerance:
            return False, (
                f"HUD net_profit mismatch: expected {expected_net:.2f}, got {actual_net:.2f}"
            )
        return True, "HUD equation balances"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HudNumbers":
        return cls(**data)


@dataclass
class BlurSpan:
    id: str
    label: str
    start_s: float
    end_s: float
    x: int
    y: int
    width: int
    height: int
    radius: int = 12
    downscale_factor: int = 12
    sigma: float = 9.0
    is_blanket: bool = False
    dropped_frames: int = 0
    constant_geometry: bool = True

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlurSpan":
        return cls(**data)


@dataclass
class WebcamRect:
    x: int
    y: int
    width: int
    height: int

    def as_rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebcamRect":
        return cls(**data)


@dataclass
class WindowPaneMask:
    id: str
    exclude_behind_head: bool
    polygon_norm: list[list[float]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WindowPaneMask":
        return cls(**data)


@dataclass
class OverlayItem:
    id: str
    kind: str  # quick_chip | deep_graphic | heavy_card | agenda | hud | tab_bar | bubble | mention_card
    title: str
    start_s: float
    end_s: float
    x: int
    y: int
    width: int
    height: int
    priority: int = 2  # 1: face/voice, 2: subject/product/screen, 3: energy_edits, 4: commentary
    is_wild: bool = False
    is_cue_exempt: bool = False
    is_persistent: bool = False
    is_grid_exempt: bool = False
    asset_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OverlayItem":
        return cls(**data)


@dataclass
class CutProposal:
    id: str
    start_s: float
    end_s: float
    reason: str
    approved: bool = False
    is_short_pause: bool = False
    start_rms_db: float | None = None
    end_rms_db: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CutProposal":
        return cls(**data)


@dataclass
class MentionItem:
    raw_token: str
    official_name: str
    url: str
    category: str
    is_private_business: bool
    timestamps: list[float] = field(default_factory=list)
    on_screen: bool = False
    visual_asset: str = ""
    overlay_id: str = ""
    skipped_by_markus: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MentionItem":
        return cls(**data)


@dataclass
class OpusClipCandidate:
    clip_id: str
    title: str
    transcript_text: str
    virality_score: float
    mapped_start_s: float | None = None
    mapped_end_s: float | None = None
    start_rms_db: float | None = None
    end_rms_db: float | None = None
    approved: bool = False
    raw_source_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpusClipCandidate":
        return cls(**data)


@dataclass
class AvatarPlacement:
    enabled: bool = True
    center_x: int = 1820
    center_y: int = 940
    faces_left: bool = True
    flipped: bool = False
    composite_above_all_blurs: bool = True
    asset_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AvatarPlacement":
        return cls(**data)


@dataclass
class ZoomEvent:
    id: str
    start_s: float
    peak_s: float
    snap_back_s: float
    scale_max: float = 1.18
    anchor: list[int] = field(default_factory=lambda: [0, 1080])
    is_dramatic: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ZoomEvent":
        return cls(**data)


@dataclass
class EditPlan:
    job_id: str
    source_video: str
    mode: str = "longform"  # longform | deepdive | short
    hud: HudNumbers | None = None
    webcam_rect: WebcamRect | None = None
    face_box: Rect | None = None
    blur_spans: list[BlurSpan] = field(default_factory=list)
    window_masks: list[WindowPaneMask] = field(default_factory=list)
    overlays: list[OverlayItem] = field(default_factory=list)
    cuts: list[CutProposal] = field(default_factory=list)
    mentions: list[MentionItem] = field(default_factory=list)
    opusclip_candidates: list[OpusClipCandidate] = field(default_factory=list)
    avatar: AvatarPlacement = field(default_factory=AvatarPlacement)
    zooms: list[ZoomEvent] = field(default_factory=list)
    swear_spans: list[dict[str, Any]] = field(default_factory=list)
    tv_icon_enabled: bool = False  # 24 Nov 2026: NO TV icon on episodes
    youtube_synthetic_flag: bool = False  # 31 Oct 2026: OFF for real Markus footage
    description_ai_line: str = "Made with AI tools."
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source_video": self.source_video,
            "mode": self.mode,
            "hud": self.hud.to_dict() if self.hud else None,
            "webcam_rect": self.webcam_rect.to_dict() if self.webcam_rect else None,
            "face_box": self.face_box.to_dict() if self.face_box else None,
            "blur_spans": [b.to_dict() for b in self.blur_spans],
            "window_masks": [w.to_dict() for w in self.window_masks],
            "overlays": [o.to_dict() for o in self.overlays],
            "cuts": [c.to_dict() for c in self.cuts],
            "mentions": [m.to_dict() for m in self.mentions],
            "opusclip_candidates": [c.to_dict() for c in self.opusclip_candidates],
            "avatar": self.avatar.to_dict(),
            "zooms": [z.to_dict() for z in self.zooms],
            "swear_spans": self.swear_spans,
            "tv_icon_enabled": self.tv_icon_enabled,
            "youtube_synthetic_flag": self.youtube_synthetic_flag,
            "description_ai_line": self.description_ai_line,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditPlan":
        return cls(
            job_id=data["job_id"],
            source_video=data.get("source_video", ""),
            mode=data.get("mode", "longform"),
            hud=HudNumbers.from_dict(data["hud"]) if data.get("hud") else None,
            webcam_rect=WebcamRect.from_dict(data["webcam_rect"]) if data.get("webcam_rect") else None,
            face_box=Rect.from_dict(data["face_box"]) if data.get("face_box") else None,
            blur_spans=[BlurSpan.from_dict(b) for b in data.get("blur_spans", [])],
            window_masks=[WindowPaneMask.from_dict(w) for w in data.get("window_masks", [])],
            overlays=[OverlayItem.from_dict(o) for o in data.get("overlays", [])],
            cuts=[CutProposal.from_dict(c) for c in data.get("cuts", [])],
            mentions=[MentionItem.from_dict(m) for m in data.get("mentions", [])],
            opusclip_candidates=[OpusClipCandidate.from_dict(c) for c in data.get("opusclip_candidates", [])],
            avatar=AvatarPlacement.from_dict(data["avatar"]) if data.get("avatar") else AvatarPlacement(),
            zooms=[ZoomEvent.from_dict(z) for z in data.get("zooms", [])],
            swear_spans=list(data.get("swear_spans", [])),
            tv_icon_enabled=bool(data.get("tv_icon_enabled", False)),
            youtube_synthetic_flag=bool(data.get("youtube_synthetic_flag", False)),
            description_ai_line=data.get("description_ai_line", "Made with AI tools."),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class GateResult:
    gate_id: str
    name: str
    passed: bool
    summary: str
    details: list[str] = field(default_factory=list)
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GateResult":
        return cls(**data)


@dataclass
class PreflightReport:
    job_id: str
    checked_at_aest: str
    passed: bool
    gates: list[GateResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "checked_at_aest": self.checked_at_aest,
            "passed": self.passed,
            "gates": [g.to_dict() for g in self.gates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreflightReport":
        return cls(
            job_id=data["job_id"],
            checked_at_aest=data["checked_at_aest"],
            passed=bool(data["passed"]),
            gates=[GateResult.from_dict(g) for g in data.get("gates", [])],
        )
