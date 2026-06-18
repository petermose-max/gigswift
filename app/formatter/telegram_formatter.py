"""Telegram formatter: MarkdownV2 post (design section 9) with an attached card.

The publisher sends this with ``parse_mode="MarkdownV2"``, so all literal/dynamic
text is escaped via :func:`escape_markdownv2`. Intentional structure — the ``*``
around bold labels, the ``[ ]( )`` of the inline link, and the ``_`` italics — is
left unescaped.
"""

from app.formatter.base import (
    BaseFormatter,
    format_pay_range,
    is_entry_level,
    placeholder_job_id,
)
from app.formatter.image import safe_generate_card
from app.schemas.job import RawJobSchema
from app.schemas.post import PostCreateSchema

# Telegram MarkdownV2 reserved characters (19). Backslash is listed FIRST so it is
# escaped before the others — otherwise the backslashes prepended to the remaining
# characters below would themselves be doubled.
_MARKDOWNV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


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
    """Formats a job into a longer-form Telegram MarkdownV2 post."""

    platform = "telegram"

    def format(self, job: RawJobSchema) -> PostCreateSchema:
        image_path = safe_generate_card(job)

        pay = format_pay_range(job, unit="hour") or "Not specified"
        requirements = (
            "None — training provided" if is_entry_level(job) else "See listing for details"
        )

        lines = [
            "📢 New Opportunity",
            "",
            f"*Role:* {escape_markdownv2(job.title)}",
            f"*Pay:* {escape_markdownv2(pay)}",
            f"*Location:* {escape_markdownv2('Remote (Worldwide)')}",
            f"*Requirements:* {escape_markdownv2(requirements)}",
        ]
        if job.apply_url:
            lines += ["", f"[{escape_markdownv2('Apply here')}]({_escape_url(job.apply_url)})"]
        lines += ["", "_Posted by GigSwift Agent_"]

        return PostCreateSchema(
            job_id=placeholder_job_id(job),
            platform=self.platform,
            content="\n".join(lines),
            image_path=image_path,
        )
