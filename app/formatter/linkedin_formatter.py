"""LinkedIn formatter: a concise, professional plain-text share (no card for v1).

Uses :func:`extract_smart_summary` for a one-line summary and key requirements,
keeps three hashtags, and caps the post at 700 characters.
"""

from app.formatter.base import (
    BaseFormatter,
    extract_smart_summary,
    format_pay_amounts,
    placeholder_job_id,
    split_company_title,
)
from app.schemas.job import RawJobSchema
from app.schemas.post import PostCreateSchema

MAX_LINKEDIN_LENGTH = 700
_MAX_REQUIREMENTS = 3

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
    """Formats a job into a professional LinkedIn post (3 hashtags, <=700 chars)."""

    platform = "linkedin"

    def format(self, job: RawJobSchema) -> PostCreateSchema:
        _, title = split_company_title(job.title)
        summary = extract_smart_summary(job.description)
        requirements = summary["requirements"][:_MAX_REQUIREMENTS] or ["Open to all levels"]
        blurb = summary["summary_line"] or summary["what_you_do"]
        pay = format_pay_amounts(job)
        hashtags = self._hashtags(job)

        content = self._build(title, pay, blurb, requirements, job.apply_url, hashtags)
        if len(content) > MAX_LINKEDIN_LENGTH:
            title = self._shorten_title(title, len(content) - MAX_LINKEDIN_LENGTH)
            content = self._build(title, pay, blurb, requirements, job.apply_url, hashtags)
        if len(content) > MAX_LINKEDIN_LENGTH:
            content = content[:MAX_LINKEDIN_LENGTH].rstrip()

        return PostCreateSchema(
            job_id=placeholder_job_id(job),
            platform=self.platform,
            content=content,
            image_path=None,  # LinkedIn image upload skipped for v1
        )

    def _build(
        self,
        title: str,
        pay: str | None,
        blurb: str | None,
        requirements: list[str],
        apply_url: str,
        hashtags: str,
    ) -> str:
        lines = [f"Remote Opportunity: {title}", ""]
        if pay:  # pay already carries its unit (e.g. "$45-$85/hr" or "$80k-$120k/year")
            lines.append(f"💰 {pay}")
        lines.append("📍 Remote (Worldwide)")
        if blurb:
            lines += ["", blurb]
        lines += ["", "Requirements:"]
        lines += [f"- {req}" for req in requirements]
        if apply_url:
            lines += ["", f"Apply: {apply_url}"]
        lines += ["", hashtags]
        return "\n".join(lines)

    def _shorten_title(self, title: str, overflow: int) -> str:
        keep = max(1, len(title) - overflow - 1)
        return f"{title[:keep].rstrip()}…"

    def _hashtags(self, job: RawJobSchema) -> str:
        text = f"{job.title} {job.description}".lower()
        topical = "#GigEconomy"
        for keyword, tag in _KEYWORD_HASHTAGS.items():
            if keyword in text:
                topical = tag
                break
        return f"#RemoteWork #Hiring {topical}"
