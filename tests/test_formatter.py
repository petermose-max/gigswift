"""Tests for the formatters, the smart summariser, and the Pillow image cards."""

import io
import os
from collections.abc import Callable

import pytest
from PIL import Image

from app.formatter import image as image_mod
from app.formatter.base import extract_smart_summary, format_pay_amounts
from app.formatter.linkedin_formatter import MAX_LINKEDIN_LENGTH, LinkedInFormatter
from app.formatter.telegram_formatter import TelegramFormatter
from app.formatter.x_formatter import MAX_TWEET_LENGTH, XFormatter
from app.schemas.job import RawJobSchema

MakeJob = Callable[..., RawJobSchema]

_STRUCTURED_DESCRIPTION = (
    "About the role: You will enter and maintain data in spreadsheets and databases.\n"
    "Requirements:\n"
    "- Laptop or computer\n"
    "- Stable internet connection\n"
    "- Good written English\n"
    "- Attention to detail\n"
    "- A fifth requirement that must be dropped\n"
)

# We Work Remotely / MyJobMag style: noise (Headquarters/URL/About) before content.
_WWR_DESCRIPTION = (
    "Headquarters: United States\n"
    "URL: https://example.com\n"
    "\n"
    "About Us\n"
    "Close is a bootstrapped, profitable startup building sales communication software.\n"
    "\n"
    "Requirements\n"
    "- 5+ years of software engineering experience\n"
    "- Strong proficiency with Python and async frameworks\n"
    "- Experience building and scaling REST APIs\n"
    "- Excellent written communication skills\n"
)


@pytest.fixture(autouse=True)
def _isolate_card_dir(tmp_path, monkeypatch) -> None:
    """Write generated cards into a per-test temp dir instead of /tmp."""
    monkeypatch.setattr(image_mod, "CARD_DIR", str(tmp_path / "cards"))


# --------------------------------------------------------------------------- #
# extract_smart_summary
# --------------------------------------------------------------------------- #
def test_extract_smart_summary_returns_expected_keys() -> None:
    result = extract_smart_summary(_STRUCTURED_DESCRIPTION)
    assert set(result) == {"what_you_do", "requirements", "summary_line"}
    assert isinstance(result["requirements"], list)
    assert result["what_you_do"] is None or isinstance(result["what_you_do"], str)
    assert result["summary_line"] is None or isinstance(result["summary_line"], str)


def test_extract_smart_summary_requirements_capped_at_four() -> None:
    result = extract_smart_summary(_STRUCTURED_DESCRIPTION)
    assert len(result["requirements"]) <= 4
    assert "Laptop or computer" in result["requirements"]


def test_extract_smart_summary_handles_empty_description() -> None:
    result = extract_smart_summary("")
    assert result == {"what_you_do": None, "requirements": [], "summary_line": None}


def test_extract_smart_summary_finds_requirements_despite_noise_prefix() -> None:
    # WWR-style descriptions front-load Headquarters/URL/About noise.
    result = extract_smart_summary(_WWR_DESCRIPTION)
    assert 1 <= len(result["requirements"]) <= 4
    joined = " ".join(result["requirements"]).lower()
    assert "experience" in joined or "python" in joined
    # the noise lines never become the summary
    summary = (result["summary_line"] or "").lower()
    assert not summary.startswith(("headquarters", "url", "about us"))


# --------------------------------------------------------------------------- #
# X formatter (unchanged behaviour)
# --------------------------------------------------------------------------- #
def test_x_post_never_exceeds_280(make_raw_job: MakeJob) -> None:
    jobs = [
        make_raw_job(),
        make_raw_job(title="Senior Staff Principal " * 40 + "Engineer"),
        make_raw_job(pay_min=None, pay_max=None, title="No Pay Gig"),
    ]
    for job in jobs:
        assert len(XFormatter().format(job).content) <= MAX_TWEET_LENGTH


def test_x_attaches_image_path(make_raw_job: MakeJob) -> None:
    post = XFormatter().format(make_raw_job())
    assert post.platform == "x"
    assert post.image_path is not None
    assert os.path.exists(post.image_path)


# --------------------------------------------------------------------------- #
# Telegram formatter
# --------------------------------------------------------------------------- #
def test_telegram_contains_apply_link(make_raw_job: MakeJob) -> None:
    job = make_raw_job()
    post = TelegramFormatter().format(job)
    assert post.platform == "telegram"
    assert f"[Apply here]({job.apply_url})" in post.content


def test_telegram_post_uses_briefcase_emoji(make_raw_job: MakeJob) -> None:
    assert "💼" in TelegramFormatter().format(make_raw_job()).content


def test_telegram_post_has_no_agent_footer(make_raw_job: MakeJob) -> None:
    assert "Agent" not in TelegramFormatter().format(make_raw_job()).content


def test_telegram_post_never_says_see_listing(make_raw_job: MakeJob) -> None:
    # Even a sparse description must yield something useful, not a placeholder.
    job = make_raw_job(description="Quick remote gig.")
    assert "See listing for details" not in TelegramFormatter().format(job).content


def test_telegram_post_omits_worldwide(make_raw_job: MakeJob) -> None:
    assert "(Worldwide)" not in TelegramFormatter().format(make_raw_job()).content


def test_telegram_post_ends_with_gigswift_handle(make_raw_job: MakeJob) -> None:
    content = TelegramFormatter().format(make_raw_job()).content
    assert content.rstrip("_").endswith("@GigSwift")


# --------------------------------------------------------------------------- #
# LinkedIn formatter
# --------------------------------------------------------------------------- #
def test_linkedin_post_under_700_with_link_and_pay(make_raw_job: MakeJob) -> None:
    job = make_raw_job()
    post = LinkedInFormatter().format(job)
    assert post.platform == "linkedin"
    assert len(post.content) <= MAX_LINKEDIN_LENGTH
    assert job.apply_url in post.content
    assert format_pay_amounts(job) in post.content  # hyphenated pay figures present
    assert post.image_path is None


def test_linkedin_post_truncates_long_title(make_raw_job: MakeJob) -> None:
    job = make_raw_job(title="Senior Staff Principal " * 50 + "Engineer")
    assert len(LinkedInFormatter().format(job).content) <= MAX_LINKEDIN_LENGTH


# --------------------------------------------------------------------------- #
# Image cards
# --------------------------------------------------------------------------- #
def test_all_four_image_variants_render_valid_png(make_raw_job: MakeJob) -> None:
    job = make_raw_job(title="Acme Corp: Data Entry Clerk", description=_STRUCTURED_DESCRIPTION)
    for variant in range(4):
        img = image_mod.render_card(job, variant)
        assert img.size == (image_mod.CARD_WIDTH, image_mod.CARD_HEIGHT)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        with Image.open(buffer) as reopened:
            assert reopened.format == "PNG"
            assert reopened.size == (image_mod.CARD_WIDTH, image_mod.CARD_HEIGHT)


def test_generate_card_writes_valid_png(make_raw_job: MakeJob) -> None:
    path = image_mod.generate_card(make_raw_job())
    assert os.path.exists(path) and path.endswith(".png")
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (image_mod.CARD_WIDTH, image_mod.CARD_HEIGHT)


def test_image_card_handles_missing_pay(make_raw_job: MakeJob) -> None:
    img = image_mod.render_card(make_raw_job(pay_min=None, pay_max=None), 0)
    assert img.size == (image_mod.CARD_WIDTH, image_mod.CARD_HEIGHT)
