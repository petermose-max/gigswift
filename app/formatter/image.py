"""Pillow card generator: a branded 1200×630 PNG per job (design section 7.4)."""

import os

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger
from app.formatter.base import format_pay_range, is_entry_level
from app.pipeline.dedup import compute_content_hash
from app.schemas.job import RawJobSchema

logger = get_logger(__name__)

CARD_DIR = "/tmp/gigswift_cards"
CARD_WIDTH = 1200
CARD_HEIGHT = 630

_BG_COLOR = "#0F1117"
_AMBER = "#F59E0B"
_WHITE = "#FFFFFF"
_MUTED = "#6B7280"
_PILL_BG = "#1B2130"
_MARGIN = 64


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Load Pillow's bundled DejaVu Sans at the given size (no external fonts)."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - only on Pillow < 10.1
        return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int = 3,
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

    consumed = sum(len(line.split()) for line in lines)
    if consumed < len(words) and lines:
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}…"
    return lines


def _tags(job: RawJobSchema) -> list[str]:
    """Pill labels for the card."""
    tags = ["Remote", "Flexible"]
    if is_entry_level(job):
        tags.append("Entry Level")
    return tags


def _draw_pills(
    draw: ImageDraw.ImageDraw,
    tags: list[str],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
) -> None:
    """Draw rounded-rectangle pill labels left-to-right."""
    pad_x, pad_y, gap = 18, 10, 14
    cursor = x
    for tag in tags:
        bbox = draw.textbbox((0, 0), tag, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pill_w, pill_h = text_w + 2 * pad_x, text_h + 2 * pad_y
        draw.rounded_rectangle(
            [cursor, y, cursor + pill_w, y + pill_h],
            radius=pill_h // 2,
            fill=_PILL_BG,
            outline=_AMBER,
            width=2,
        )
        draw.text((cursor + pad_x, y + pill_h // 2), tag, font=font, fill=_AMBER, anchor="lm")
        cursor += pill_w + gap


def _draw_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    right_x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    """Draw right-aligned text ending at ``right_x``."""
    width = draw.textlength(text, font=font)
    draw.text((right_x - width, y), text, font=font, fill=fill)


def generate_card(job: RawJobSchema) -> str:
    """Render the branded card for ``job`` and return its file path.

    Idempotent: the filename is the job's content hash, so a card that already
    exists is reused rather than re-rendered.
    """
    os.makedirs(CARD_DIR, exist_ok=True)
    job_hash = compute_content_hash(job.title, job.apply_url)
    path = os.path.join(CARD_DIR, f"{job_hash}.png")
    if os.path.exists(path):
        return path

    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), _BG_COLOR)
    draw = ImageDraw.Draw(image)

    # Brand mark (top-left).
    draw.text((_MARGIN, 48), "GigSwift", font=_font(30), fill=_AMBER)

    # Pay range, large amber — gracefully handles missing pay.
    pay_text = format_pay_range(job) or "Pay: Not specified"
    draw.text((_MARGIN, 150), pay_text, font=_font(48), fill=_AMBER)

    # Title, white and faux-bold (stroke), wrapped to the card width.
    title_font = _font(32)
    y = 250
    for line in _wrap(draw, job.title, title_font, CARD_WIDTH - 2 * _MARGIN, max_lines=3):
        draw.text(
            (_MARGIN, y), line, font=title_font, fill=_WHITE, stroke_width=1, stroke_fill=_WHITE
        )
        y += 46

    # Platform pills.
    _draw_pills(draw, _tags(job), x=_MARGIN, y=max(y + 24, 430), font=_font(22))

    # Source attribution (bottom-left) and brand watermark (bottom-right).
    draw.text((_MARGIN, CARD_HEIGHT - 52), job.source, font=_font(18), fill=_MUTED)
    _draw_right(draw, "GigSwift Agent", CARD_WIDTH - _MARGIN, CARD_HEIGHT - 52, _font(20), _MUTED)

    image.save(path, format="PNG")
    logger.debug("Generated card %s", path)
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
