"""Tests for the X/Telegram formatters and the Pillow image card."""

import os
from collections.abc import Callable

import pytest
from PIL import Image

from app.formatter import image as image_mod
from app.formatter.telegram_formatter import TelegramFormatter
from app.formatter.x_formatter import MAX_TWEET_LENGTH, XFormatter
from app.schemas.job import RawJobSchema

MakeJob = Callable[..., RawJobSchema]


@pytest.fixture(autouse=True)
def _isolate_card_dir(tmp_path, monkeypatch) -> None:
    """Write generated cards into a per-test temp dir instead of /tmp."""
    monkeypatch.setattr(image_mod, "CARD_DIR", str(tmp_path / "cards"))


def test_x_post_never_exceeds_280(make_raw_job: MakeJob) -> None:
    jobs = [
        make_raw_job(),
        make_raw_job(title="Senior Staff Principal " * 40 + "Engineer"),  # absurdly long
        make_raw_job(pay_min=None, pay_max=None, title="No Pay Gig"),
    ]
    for job in jobs:
        post = XFormatter().format(job)
        assert len(post.content) <= MAX_TWEET_LENGTH


def test_x_attaches_image_path(make_raw_job: MakeJob) -> None:
    post = XFormatter().format(make_raw_job())
    assert post.platform == "x"
    assert post.image_path is not None
    assert os.path.exists(post.image_path)


def test_telegram_contains_apply_link(make_raw_job: MakeJob) -> None:
    job = make_raw_job()
    post = TelegramFormatter().format(job)
    assert post.platform == "telegram"
    assert f"[Apply here]({job.apply_url})" in post.content


def test_image_card_is_valid_png(make_raw_job: MakeJob) -> None:
    path = image_mod.generate_card(make_raw_job())
    assert os.path.exists(path) and path.endswith(".png")
    with Image.open(path) as img:
        assert img.format == "PNG"
        assert img.size == (image_mod.CARD_WIDTH, image_mod.CARD_HEIGHT)


def test_image_card_handles_missing_pay(make_raw_job: MakeJob) -> None:
    path = image_mod.generate_card(make_raw_job(pay_min=None, pay_max=None))
    assert os.path.exists(path)  # renders gracefully without pay
    with Image.open(path) as img:
        assert img.size == (image_mod.CARD_WIDTH, image_mod.CARD_HEIGHT)
