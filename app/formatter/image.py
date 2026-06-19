"""Pillow card generator: a branded 1200x630 PNG per job.

Four professional layout variants rotate deterministically on the job's content
hash, so a feed of posts looks varied. Card content comes from
:func:`extract_smart_summary` (requirements + a one-line summary). Pay figures use a
hyphen-minus (never an en dash). Each card shows requirements when available (else a
description summary), the apply URL near the bottom, and a "GigSwift" mark.
"""

import os
import re

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger
from app.formatter.base import (
    clean_description_preview,
    extract_smart_summary,
    format_pay_amounts,
    split_company_title,
)
from app.pipeline.dedup import compute_content_hash
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)

CARD_DIR = "/tmp/gigswift_cards"
CARD_WIDTH = 1200
CARD_HEIGHT = 630

# (company, title, pay, summary, requirements, apply_url)
_Fields = tuple[str | None, str, str | None, str | None, list[str], str]

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Load Pillow's bundled DejaVu Sans at the given size (no external fonts)."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - only on Pillow < 10.1
        return ImageFont.load_default()


def _blend(fg: str, bg: str, alpha: float) -> str:
    """Blend ``fg`` over ``bg`` at ``alpha`` opacity, returning a #RRGGBB string."""
    f = tuple(int(fg[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(bg[i : i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(round(bi * (1 - alpha) + fi * alpha) for fi, bi in zip(f, b, strict=True))
    return "#{:02X}{:02X}{:02X}".format(*mixed)


def _trunc(text: str, limit: int) -> str:
    """Trim text to ``limit`` chars at a word boundary, adding an ellipsis."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{(cut or text[:limit]).rstrip()}…"


def _display_url(url: str) -> str:
    """Strip the scheme and truncate a URL for compact display on a card."""
    text = _SCHEME_RE.sub("", url or "").rstrip("/")
    return f"{text[:50]}..." if len(text) > 50 else text


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Word-wrap ``text`` to ``max_width``, truncating to ``max_lines`` with an ellipsis."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines and current:
        lines.append(current)
    if sum(len(line.split()) for line in lines) < len(words) and lines:
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}…"
    return lines


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    line_height: int,
    *,
    x: int = 0,
    center: bool = False,
    stroke: int = 0,
) -> None:
    for line in lines:
        if center:
            draw.text(
                (CARD_WIDTH // 2, y),
                line,
                font=font,
                fill=fill,
                anchor="ma",
                stroke_width=stroke,
                stroke_fill=fill,
            )
        else:
            draw.text((x, y), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=fill)
        y += line_height


def _draw_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    right_x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    draw.text((right_x - draw.textlength(text, font=font), y), text, font=font, fill=fill)


def _draw_req_list(
    draw: ImageDraw.ImageDraw,
    requirements: list[str],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    *,
    center: bool = False,
    line_height: int = 30,
    max_items: int = 3,
    max_chars: int = 45,
) -> None:
    """Draw up to three requirements as dash-prefixed lines (Pillow has no emoji)."""
    for req in requirements[:max_items]:
        text = f"-  {_trunc(req, max_chars)}"
        if center:
            draw.text((CARD_WIDTH // 2, y), text, font=font, fill=fill, anchor="ma")
        else:
            draw.text((x, y), text, font=font, fill=fill)
        y += line_height


def _draw_info(
    draw: ImageDraw.ImageDraw,
    summary: str | None,
    requirements: list[str],
    *,
    x: int,
    summary_y: int,
    req_y: int,
    summary_font: ImageFont.FreeTypeFont,
    summary_fill: str,
    req_font: ImageFont.FreeTypeFont,
    req_fill: str,
    max_width: int,
    center: bool = False,
) -> None:
    """Show a one/two-line summary plus a requirements list.

    When there are no requirements, the summary expands to fill the space so the
    card never has an empty gap.
    """
    if summary:
        lines = _wrap(draw, summary, summary_font, max_width, 2 if requirements else 4)
        _draw_wrapped(draw, lines, summary_y, summary_font, summary_fill, 28, x=x, center=center)
    if requirements:
        _draw_req_list(draw, requirements, x, req_y, req_font, req_fill, center=center)


# --------------------------------------------------------------------------- #
# Variants
# --------------------------------------------------------------------------- #
def _variant_dark_command(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements, apply_url = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, w, h], fill="#0D1117")
    draw.rectangle([0, 0, 10, h], fill="#F59E0B")
    x = 50
    if company:
        draw.text((x, 40), _trunc(company, 48), font=_font(20), fill="#6B7280")
    _draw_wrapped(
        draw,
        _wrap(draw, title, _font(42), w - x - 40, 2),
        78,
        _font(42),
        "#FFFFFF",
        52,
        x=x,
        stroke=1,
    )
    draw.line([(0, 196), (w, 196)], fill="#1F2937", width=1)
    if pay:
        draw.text((x, 214), pay, font=_font(32), fill="#F59E0B")
    _draw_info(
        draw,
        summary,
        requirements,
        x=x,
        summary_y=278,
        req_y=362,
        summary_font=_font(18),
        summary_fill="#9CA3AF",
        req_font=_font(17),
        req_fill="#9CA3AF",
        max_width=w - x - 40,
    )
    if apply_url:
        draw.text((x, h - 58), _display_url(apply_url), font=_font(14), fill="#6B7280")
    draw.rectangle([0, h - 3, w, h], fill="#F59E0B")
    _draw_right(draw, "GigSwift", w - 20, h - 34, _font(14), "#374151")


def _variant_navy_precision(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements, apply_url = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, w, h], fill="#050A1E")
    draw.rectangle([0, 0, w, 80], fill="#0A1628")
    draw.text((40, 32), "REMOTE OPPORTUNITY", font=_font(13), fill="#3B82F6")
    if company:
        draw.text((w // 2, 106), _trunc(company, 48), font=_font(22), fill="#60A5FA", anchor="ma")
    _draw_wrapped(
        draw,
        _wrap(draw, title, _font(46), int(w * 0.86), 2),
        150,
        _font(46),
        "#FFFFFF",
        54,
        center=True,
        stroke=1,
    )
    draw.line([(int(w * 0.12), 276), (int(w * 0.88), 276)], fill="#1E3A5F", width=2)
    if pay:
        draw.text((w // 2, 296), pay, font=_font(30), fill="#F59E0B", anchor="ma")
    _draw_info(
        draw,
        summary,
        requirements,
        x=0,
        summary_y=348,
        req_y=428,
        summary_font=_font(17),
        summary_fill="#94A3B8",
        req_font=_font(16),
        req_fill="#60A5FA",
        max_width=int(w * 0.8),
        center=True,
    )
    if apply_url:
        draw.text(
            (w // 2, h - 56), _display_url(apply_url), font=_font(14), fill="#64748B", anchor="ma"
        )
    _draw_right(draw, "GigSwift", w - 20, h - 34, _font(14), "#1E3A5F")


def _variant_split_panel(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements, apply_url = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, 880, h], fill="#111111")
    draw.rectangle([880, 0, w, h], fill="#F59E0B")
    panel_cx = 880 + (w - 880) // 2
    if pay:  # pay self-describes its unit (/hr or /year) — no separate label needed
        draw.text(
            (panel_cx, 255),
            pay,
            font=_font(26),
            fill="#111111",
            anchor="ma",
            stroke_width=1,
            stroke_fill="#111111",
        )
    else:
        draw.text((panel_cx, 260), "Remote", font=_font(24), fill="#111111", anchor="ma")
    draw.text((panel_cx, h - 40), "GigSwift", font=_font(14), fill="#7C5500", anchor="ma")
    x = 40
    if company:
        draw.text((x, 50), _trunc(company, 36), font=_font(22), fill="#D97706")
    _draw_wrapped(
        draw, _wrap(draw, title, _font(40), 800, 2), 100, _font(40), "#FFFFFF", 48, x=x, stroke=1
    )
    _draw_info(
        draw,
        summary,
        requirements,
        x=x,
        summary_y=248,
        req_y=360,
        summary_font=_font(18),
        summary_fill="#A8966E",
        req_font=_font(17),
        req_fill="#A8966E",
        max_width=800,
    )
    if apply_url:
        draw.text((x, h - 50), _display_url(apply_url), font=_font(14), fill="#6B7280")


def _variant_emerald_edge(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements, apply_url = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, w, h], fill="#0F1923")
    draw.rectangle([0, 0, 6, h], fill="#10B981")
    draw.polygon([(w - 120, 0), (w, 0), (w, 120)], fill=_blend("#10B981", "#0F1923", 0.15))
    x = 50
    if company:
        draw.text((x, 40), _trunc(company, 48), font=_font(20), fill="#10B981")
    _draw_wrapped(
        draw,
        _wrap(draw, title, _font(48), w - x - 140, 2),
        84,
        _font(48),
        "#FFFFFF",
        58,
        x=x,
        stroke=2,
    )
    if pay:
        draw.text((x, 228), pay, font=_font(30), fill="#F59E0B")
    _draw_info(
        draw,
        summary,
        requirements,
        x=x,
        summary_y=292,
        req_y=376,
        summary_font=_font(17),
        summary_fill="#6B7280",
        req_font=_font(17),
        req_fill="#10B981",
        max_width=w - x - 60,
    )
    if apply_url:
        draw.text((x, h - 58), _display_url(apply_url), font=_font(14), fill="#6B7280")
    draw.rectangle([0, h - 14, w, h - 10], fill="#10B981")
    _draw_right(draw, "GigSwift", w - 20, h - 34, _font(14), "#374151")


_VARIANTS = (
    _variant_dark_command,
    _variant_navy_precision,
    _variant_split_panel,
    _variant_emerald_edge,
)


def _card_fields(job: RawJobSchema) -> _Fields:
    company, title = split_company_title(job.title)
    summary = extract_smart_summary(job.description)
    # Always show something: summary line, else the first task, else a raw preview.
    blurb = (
        summary["summary_line"]
        or summary["what_you_do"]
        or clean_description_preview(job.description, max_len=100)
    )
    requirements: list[str] = summary["requirements"]  # type: ignore[assignment]
    return company, title, format_pay_amounts(job), blurb, requirements, job.apply_url


def render_card(job: RawJobSchema, variant: int) -> Image.Image:
    """Render one of the four card variants for ``job`` as a Pillow image."""
    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), "#000000")
    draw = ImageDraw.Draw(image)
    _VARIANTS[variant % len(_VARIANTS)](draw, _card_fields(job))
    return image


def generate_card(job: RawJobSchema) -> str:
    """Render the branded card for ``job`` and return its file path.

    The variant is chosen deterministically from the content hash. Idempotent: the
    filename is the content hash, so an existing card is reused, not re-rendered.
    """
    os.makedirs(CARD_DIR, exist_ok=True)
    job_hash = compute_content_hash(job.title, job.apply_url)
    path = os.path.join(CARD_DIR, f"{job_hash}.png")
    if os.path.exists(path):
        return path

    variant = int(job_hash[:8], 16) % len(_VARIANTS)
    render_card(job, variant).save(path, format="PNG")
    logger.debug("Generated card %s (variant %d)", path, variant)
    return path


def safe_generate_card(job: RawJobSchema) -> str | None:
    """Generate a card, returning ``None`` (and logging) on any failure."""
    try:
        return generate_card(job)
    except Exception:
        logger.warning(
            "Card generation failed for %r; continuing without image", job.title, exc_info=True
        )
        return None
