"""LinkedIn formatter: a concise, professional text share.

Professional tone, at most three relevant hashtags, capped at 700 characters (a
good LinkedIn length). No image card is attached for v1.
"""

from app.formatter.base import (
    BaseFormatter,
    format_pay_range,
    is_entry_level,
    placeholder_job_id,
)
from app.schemas.job import RawJobSchema
from app.schemas.post import PostCreateSchema

MAX_LINKEDIN_LENGTH = 700

# Title/description keywords mapped to a single professional topical hashtag.
_KEYWORD_HASHTAGS: dict[str, str] = {
    "data": "#DataJobs",
    "ai": "#AI",
    "machine learning": "#AI",
    "design": "#Design",
    "writing": "#Writing",
    "developer": "#TechJobs",
    "engineer": "#TechJobs",
    "marketing": "#Marketing",
    "customer": "#CustomerService",
}


class LinkedInFormatter(BaseFormatter):
    """Formats a job into a professional LinkedIn post (<=3 hashtags, <=700 chars)."""

    platform = "linkedin"

    def format(self, job: RawJobSchema) -> PostCreateSchema:
        pay = format_pay_range(job, unit="hour") or "Not specified"
        requirements = "No experience needed" if is_entry_level(job) else "See listing for details"

        content = self._build(job, job.title, pay, requirements)
        if len(content) > MAX_LINKEDIN_LENGTH:
            content = self._build(job, self._shorten_title(job, content), pay, requirements)
        if len(content) > MAX_LINKEDIN_LENGTH:
            content = content[:MAX_LINKEDIN_LENGTH].rstrip()

        return PostCreateSchema(
            job_id=placeholder_job_id(job),
            platform=self.platform,
            content=content,
            image_path=None,  # LinkedIn image upload skipped for v1
        )

    def _build(self, job: RawJobSchema, title: str, pay: str, requirements: str) -> str:
        lines = [
            "New remote opportunity:",
            "",
            f"Role: {title}",
            f"Pay: {pay}",
            "Location: Remote (Worldwide)",
            f"Requirements: {requirements}",
        ]
        if job.apply_url:
            lines += ["", f"Apply: {job.apply_url}"]
        lines += ["", self._hashtags(job)]
        return "\n".join(lines)

    def _shorten_title(self, job: RawJobSchema, full_content: str) -> str:
        """Trim the title by the overflow so the rebuilt post fits the limit."""
        overflow = len(full_content) - MAX_LINKEDIN_LENGTH
        keep = max(1, len(job.title) - overflow - 1)
        return f"{job.title[:keep].rstrip()}…"

    def _hashtags(self, job: RawJobSchema) -> str:
        # Always exactly three: keep it professional, no hashtag spam.
        tags = ["#RemoteWork", "#GigEconomy", "#Hiring"]
        text = f"{job.title} {job.description}".lower()
        for keyword, tag in _KEYWORD_HASHTAGS.items():
            if keyword in text:
                tags[1] = tag  # swap in one topical tag, still three total
                break
        return " ".join(tags[:3])
