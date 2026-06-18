"""X (Twitter) formatter: a <=280-char post with an attached card image."""

from app.formatter.base import (
    BaseFormatter,
    format_pay_range,
    is_entry_level,
    placeholder_job_id,
)
from app.formatter.image import safe_generate_card
from app.schemas.job import RawJobSchema
from app.schemas.post import PostCreateSchema

MAX_TWEET_LENGTH = 280

# Title/description keywords mapped to topical hashtags.
_KEYWORD_HASHTAGS: dict[str, str] = {
    "data": "#DataJobs",
    "ai": "#AI",
    "machine learning": "#AI",
    "design": "#Design",
    "writing": "#Writing",
    "content": "#Content",
    "developer": "#TechJobs",
    "engineer": "#TechJobs",
    "customer": "#CustomerService",
    "virtual assistant": "#VirtualAssistant",
    "marketing": "#Marketing",
}
_MAX_HASHTAGS = 6


class XFormatter(BaseFormatter):
    """Formats a job into an X post following the section 9 layout."""

    platform = "x"

    def format(self, job: RawJobSchema) -> PostCreateSchema:
        image_path = safe_generate_card(job)

        content = self._build(job, job.title)
        if len(content) > MAX_TWEET_LENGTH:
            content = self._build(job, self._shorten_title(job, content))
        # Final hard guarantee that the post never exceeds the limit.
        if len(content) > MAX_TWEET_LENGTH:
            content = content[:MAX_TWEET_LENGTH].rstrip()

        return PostCreateSchema(
            job_id=placeholder_job_id(job),
            platform=self.platform,
            content=content,
            image_path=image_path,
        )

    def _build(self, job: RawJobSchema, title: str) -> str:
        pay = format_pay_range(job)
        header = f"💰 {pay} | {title}" if pay else f"💼 {title}"

        lines = [header, "", "🕒 Remote • Flexible hours"]
        if is_entry_level(job):
            lines.append("✅ No experience required")
        lines.append("📍 Work from anywhere")
        if job.apply_url:
            lines += ["", f"Apply → {job.apply_url}"]
        lines += ["", self._hashtags(job)]
        return "\n".join(lines).strip()

    def _shorten_title(self, job: RawJobSchema, full_content: str) -> str:
        """Trim the title by exactly the overflow so the rebuilt post fits."""
        overflow = len(full_content) - MAX_TWEET_LENGTH
        keep = max(1, len(job.title) - overflow - 1)
        return f"{job.title[:keep].rstrip()}…"

    def _hashtags(self, job: RawJobSchema) -> str:
        tags = ["#RemoteJobs", "#GigWork"]
        text = f"{job.title} {job.description}".lower()
        for keyword, tag in _KEYWORD_HASHTAGS.items():
            if keyword in text and tag not in tags:
                tags.append(tag)
        if is_entry_level(job) and "#EntryLevel" not in tags:
            tags.append("#EntryLevel")
        tags.append("#HiringNow")

        ordered: list[str] = []
        for tag in tags:
            if tag not in ordered:
                ordered.append(tag)
        return " ".join(ordered[:_MAX_HASHTAGS])
