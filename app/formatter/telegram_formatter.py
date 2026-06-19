"""Telegram formatter: a clean MarkdownV2 post with an attached card.

The publisher sends this with ``parse_mode="MarkdownV2"``, so all literal/dynamic
text is escaped via :func:`escape_markdownv2`. Intentional structure — the ``*``
around bold, the ``[ ]( )`` of the link, the ``_`` italics, and the escaped ``\\-``
bullets — is written directly.
"""

from app.formatter.base import (
    BaseFormatter,
    extract_smart_summary,
    format_pay_amounts,
    placeholder_job_id,
    split_company_title,
)
from app.formatter.image import safe_generate_card
from app.schemas.job import RawJobSchema
from app.schemas.post import PostCreateSchema

# Telegram MarkdownV2 reserved characters (19). Backslash is listed FIRST so it is
# escaped before the others — otherwise the backslashes prepended to the remaining
# characters below would themselves be doubled.
_MARKDOWNV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"

_MAX_REQUIREMENTS = 4


def escape_markdownv2(text: str) -> str:
    """Escape all 19 Telegram MarkdownV2 reserved characters with a backslash.

    Reserved set: \\ _ * [ ] ( ) ~ ` > # + - = | { } . ! — backslash is escaped
    first so the escapes added for the other characters are not doubled. Apply to
    literal/dynamic text only — never to intentional Markdown structure (the * around
    bold, the [ ]( ) of inline links) nor to a link's URL (see :func:`_escape_url`).
    """
    for char in _MARKDOWNV2_SPECIAL:
        text = text.replace(char, f"\\{char}")
    return text


def _escape_url(url: str) -> str:
    """Escape a link's URL for MarkdownV2: inside ``(...)`` only ``)`` and ``\\`` need it."""
    return url.replace("\\", "\\\\").replace(")", "\\)")


class TelegramFormatter(BaseFormatter):
    """Formats a job into a clean, well-spaced Telegram MarkdownV2 post."""

    platform = "telegram"

    def format(self, job: RawJobSchema) -> PostCreateSchema:
        image_path = safe_generate_card(job)

        company, title = split_company_title(job.title)
        summary = extract_smart_summary(job.description)
        requirements = summary["requirements"][:_MAX_REQUIREMENTS] or ["Open to all levels"]
        # Always show something useful — never "See listing for details".
        blurb = summary["summary_line"] or summary["what_you_do"]

        pay = format_pay_amounts(job)
        pay_text = f"{pay} per hour" if pay else "Not specified"

        lines = [f"💼 *{escape_markdownv2(title)}*"]
        if company:
            lines.append(f"🏢 {escape_markdownv2(company)}")
        lines += [
            "",
            f"💰 *Pay:* {escape_markdownv2(pay_text)}",
            "📍 *Location:* Remote",
        ]
        if blurb:
            lines += ["", escape_markdownv2(blurb)]
        lines += ["", "✅ *Requirements:*"]
        lines += [f"\\- {escape_markdownv2(req)}" for req in requirements]
        if job.apply_url:
            lines += ["", f"🔗 [Apply here]({_escape_url(job.apply_url)})"]
        lines += ["", "_@GigSwift_"]

        return PostCreateSchema(
            job_id=placeholder_job_id(job),
            platform=self.platform,
            content="\n".join(lines),
            image_path=image_path,
        )
