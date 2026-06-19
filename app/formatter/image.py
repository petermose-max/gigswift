"""Pillow card generator: a branded 1200x630 PNG per job.

Four professional layout variants rotate deterministically on the job's content
hash, so a feed of posts looks varied. Card content comes from
:func:`extract_smart_summary` (requirements + a one-line summary). Pay figures use a
hyphen-minus (never an en dash). The brand mark is "GigSwift".
"""

import os

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger
from app.formatter.base import (
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

_Fields = tuple[str | None, str, str | None, str | None, list[str]]


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


def _pill_size(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, pad_x: int, pad_y: int
) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0] + 2 * pad_x, bbox[3] - bbox[1] + 2 * pad_y


def _draw_pill_row(
    draw: ImageDraw.ImageDraw,
    items: list[str],
    y: int,
    font: ImageFont.FreeTypeFont,
    *,
    bg: str,
    fg: str,
    x0: int = 0,
    x1: int | None = None,
    align: str = "left",
    max_items: int = 3,
    pad_x: int = 12,
    pad_y: int = 6,
    gap: int = 10,
) -> None:
    """Draw a horizontal row of rounded pill labels, left-aligned or centered in [x0, x1]."""
    labels = [_trunc(item, 22) for item in items[:max_items] if item]
    if not labels:
        return
    x1 = CARD_WIDTH if x1 is None else x1
    sizes = [_pill_size(draw, label, font, pad_x, pad_y) for label in labels]
    total = sum(w for w, _ in sizes) + gap * (len(labels) - 1)
    cursor = x0 + ((x1 - x0) - total) // 2 if align == "center" else x0
    for label, (w, h) in zip(labels, sizes, strict=True):
        draw.rounded_rectangle([cursor, y, cursor + w, y + h], radius=h // 2, fill=bg)
        draw.text((cursor + pad_x, y + h // 2), label, font=font, fill=fg, anchor="lm")
        cursor += w + gap


# --------------------------------------------------------------------------- #
# Variants
# --------------------------------------------------------------------------- #
def _variant_dark_command(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, w, h], fill="#0D1117")
    draw.rectangle([0, 0, 10, h], fill="#F59E0B")
    x = 50
    if company:
        draw.text((x, 40), _trunc(company, 48), font=_font(20), fill="#6B7280")
    _draw_wrapped(
        draw,
        _wrap(draw, title, _font(42), w - x - 40, 2),
        80,
        _font(42),
        "#FFFFFF",
        52,
        x=x,
        stroke=1,
    )
    draw.line([(0, 220), (w, 220)], fill="#1F2937", width=1)
    if pay:
        draw.text((x, 240), f"{pay} / hour", font=_font(34), fill="#F59E0B")
    if summary:
        draw.text((x, 300), _trunc(summary, 80), font=_font(18), fill="#9CA3AF")
    _draw_pill_row(draw, requirements, 370, _font(16), bg="#1F2937", fg="#9CA3AF", x0=x)
    draw.rectangle([0, h - 3, w, h], fill="#F59E0B")
    _draw_right(draw, "GigSwift", w - 20, h - 34, _font(14), "#374151")


def _variant_navy_precision(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, w, h], fill="#050A1E")
    draw.rectangle([0, 0, w, 80], fill="#0A1628")
    draw.text((40, 32), "REMOTE OPPORTUNITY", font=_font(13), fill="#3B82F6")
    if company:
        draw.text((w // 2, 110), _trunc(company, 48), font=_font(22), fill="#60A5FA", anchor="ma")
    _draw_wrapped(
        draw,
        _wrap(draw, title, _font(46), int(w * 0.86), 2),
        160,
        _font(46),
        "#FFFFFF",
        56,
        center=True,
        stroke=1,
    )
    draw.line([(int(w * 0.1), 290), (int(w * 0.9), 290)], fill="#1E3A5F", width=2)
    if pay:
        draw.text((w // 2, 320), f"{pay} / hour", font=_font(32), fill="#F59E0B", anchor="ma")
    if summary:
        draw.text((w // 2, 380), _trunc(summary, 80), font=_font(17), fill="#94A3B8", anchor="ma")
    _draw_pill_row(
        draw, requirements, 450, _font(16), bg="#0F2044", fg="#60A5FA", x0=0, x1=w, align="center"
    )
    _draw_right(draw, "GigSwift", w - 20, h - 34, _font(14), "#1E3A5F")


def _variant_split_panel(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, 880, h], fill="#111111")
    draw.rectangle([880, 0, w, h], fill="#F59E0B")
    panel_cx = 880 + (w - 880) // 2
    if pay:
        draw.text(
            (panel_cx, 200),
            pay,
            font=_font(30),
            fill="#111111",
            anchor="ma",
            stroke_width=1,
            stroke_fill="#111111",
        )
        draw.text((panel_cx, 250), "per hour", font=_font(16), fill="#1A1A1A", anchor="ma")
    py = 300
    for req in requirements[:2]:
        label = _trunc(req, 18)
        pw, ph = _pill_size(draw, label, _font(14), 12, 6)
        px = 880 + ((w - 880) - pw) // 2
        draw.rounded_rectangle([px, py, px + pw, py + ph], radius=ph // 2, fill="#1A1A1A")
        draw.text((px + 12, py + ph // 2), label, font=_font(14), fill="#F59E0B", anchor="lm")
        py += ph + 10
    _draw_right(draw, "GigSwift", w - 20, h - 34, _font(14), "#7C5500")
    if company:
        draw.text((40, 50), _trunc(company, 36), font=_font(22), fill="#D97706")
    _draw_wrapped(
        draw, _wrap(draw, title, _font(42), 820, 3), 100, _font(42), "#FFFFFF", 50, x=40, stroke=1
    )
    if summary:
        draw.text((40, 280), _trunc(summary, 80), font=_font(18), fill="#A8966E")
    draw.text((40, 380), "Pay:", font=_font(16), fill="#F59E0B")


def _variant_emerald_edge(draw: ImageDraw.ImageDraw, fields: _Fields) -> None:
    company, title, pay, summary, requirements = fields
    w, h = CARD_WIDTH, CARD_HEIGHT
    draw.rectangle([0, 0, w, h], fill="#0F1923")
    draw.rectangle([0, 0, 6, h], fill="#10B981")
    draw.polygon([(w - 120, 0), (w, 0), (w, 120)], fill=_blend("#10B981", "#0F1923", 0.15))
    x = 50
    if company:
        draw.text((x, 40), _trunc(company, 48), font=_font(20), fill="#10B981")
    _draw_wrapped(
        draw,
        _wrap(draw, title, _font(50), w - x - 140, 2),
        90,
        _font(50),
        "#FFFFFF",
        60,
        x=x,
        stroke=2,
    )
    if pay:
        draw.text((x, 250), f"{pay} / hour", font=_font(32), fill="#F59E0B")
    if summary:
        draw.text((x, 310), _trunc(summary, 80), font=_font(17), fill="#6B7280")
    _draw_pill_row(draw, requirements, 400, _font(16), bg="#1F2937", fg="#10B981", x0=x)
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
    summary_line = summary["summary_line"] or summary["what_you_do"]
    requirements: list[str] = summary["requirements"]  # type: ignore[assignment]
    return company, title, format_pay_amounts(job), summary_line, requirements


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
