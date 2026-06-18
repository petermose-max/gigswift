"""Unit tests for the pipeline: dedup, filter, scorer, runner."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from app.models import Job
from app.pipeline.dedup import compute_content_hash, filter_new_jobs
from app.pipeline.filter import SCAM_FLAGS, filter_scams, is_scam
from app.pipeline.runner import run as run_pipeline
from app.pipeline.scorer import score_job
from app.schemas.job import RawJobSchema

MakeJob = Callable[..., RawJobSchema]


# --------------------------------------------------------------------------- #
# dedup
# --------------------------------------------------------------------------- #
def test_compute_content_hash_deterministic_and_distinct() -> None:
    h1 = compute_content_hash("Title", "https://e.com/1")
    assert h1 == compute_content_hash("Title", "https://e.com/1")  # deterministic
    assert h1 != compute_content_hash("Title", "https://e.com/2")  # url matters
    assert h1 != compute_content_hash("Other", "https://e.com/1")  # title matters
    assert len(h1) == 64


@pytest.mark.asyncio
async def test_filter_new_jobs_removes_db_duplicates(db_session, make_raw_job: MakeJob) -> None:
    seen = make_raw_job()
    fresh = make_raw_job()
    db_session.add(
        Job(
            source=seen.source,
            title=seen.title,
            description=seen.description,
            apply_url=seen.apply_url,
            content_hash=compute_content_hash(seen.title, seen.apply_url),
            pay_currency="USD",
            is_scam=False,
        )
    )
    await db_session.commit()

    result = await filter_new_jobs([seen, fresh], db_session)
    assert result == [fresh]  # the already-seen job is dropped


@pytest.mark.asyncio
async def test_filter_new_jobs_collapses_in_batch_duplicates(
    db_session, make_raw_job: MakeJob
) -> None:
    a = make_raw_job(title="Same", apply_url="https://e.com/same")
    a_dup = make_raw_job(title="Same", apply_url="https://e.com/same")  # identical hash
    b = make_raw_job()

    result = await filter_new_jobs([a, a_dup, b], db_session)
    assert len(result) == 2
    assert result[0] is a and result[1] is b  # first occurrence wins


@pytest.mark.asyncio
async def test_filter_new_jobs_empty(db_session) -> None:
    assert await filter_new_jobs([], db_session) == []


# --------------------------------------------------------------------------- #
# filter (scam detection)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("flag", SCAM_FLAGS)
def test_is_scam_detects_each_flag(flag: str, make_raw_job: MakeJob) -> None:
    assert is_scam(make_raw_job(description=f"This role needs {flag} before you start.")) is True


def test_is_scam_clean_job(make_raw_job: MakeJob) -> None:
    assert is_scam(make_raw_job(description="A normal remote engineering role.")) is False


def test_filter_scams_removes_flagged(make_raw_job: MakeJob) -> None:
    clean = make_raw_job(description="normal role")
    scam = make_raw_job(description="please send money first")
    assert filter_scams([clean, scam]) == [clean]


# --------------------------------------------------------------------------- #
# scorer (each factor)
# --------------------------------------------------------------------------- #
def test_scorer_pay_min_and_pay_max(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Worker",
        description="Office position",
        apply_url="",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.6)  # +0.4 pay_min, +0.2 pay_max


def test_scorer_entry_level_title_adds_point_two(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Entry Level Worker",
        description="Office position",
        apply_url="",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.8)  # 0.6 + 0.2


def test_scorer_remote_description_adds_point_one(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Worker",
        description="Fully remote position",
        apply_url="",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.7)  # 0.6 + 0.1


def test_scorer_valid_url_adds_point_one(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Worker",
        description="Office",
        apply_url="https://example.com/x",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.7)


def test_scorer_redirect_farm_url_gets_no_bonus(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Worker",
        description="Office",
        apply_url="https://bit.ly/x",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.6)  # redirect farm -> no +0.1


def test_scorer_scam_description_subtracts_point_five(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Worker",
        description="Office wire transfer required",
        apply_url="",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.1)  # 0.6 - 0.5


def test_scorer_all_caps_title_subtracts_point_three(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="WORKER NEEDED NOW",
        description="Office",
        apply_url="",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == pytest.approx(0.3)  # 0.6 - 0.3


def test_scorer_no_pay_subtracts_point_two(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Worker",
        description="remote worldwide",
        apply_url="https://example.com/x",
        pay_min=None,
        pay_max=None,
    )
    assert score_job(job) == pytest.approx(0.0)  # +0.1 remote +0.1 url -0.2 no pay


def test_scorer_normalises_annual_pay(make_raw_job: MakeJob) -> None:
    # 45000 / 2080 = 21.6 >= 15 -> +0.4 ; 20000 / 2080 = 9.6 < 15 -> no +0.4
    passes = make_raw_job(
        title="Worker", description="Office", apply_url="", pay_min=Decimal("45000"), pay_max=None
    )
    fails = make_raw_job(
        title="Worker", description="Office", apply_url="", pay_min=Decimal("20000"), pay_max=None
    )
    assert score_job(passes) == pytest.approx(0.4)
    assert score_job(fails) == pytest.approx(0.0)


def test_scorer_clamps_to_one(make_raw_job: MakeJob) -> None:
    job = make_raw_job(
        title="Entry Level Data Labeler - No Experience",
        description="Fully remote, work from anywhere worldwide.",
        apply_url="https://example.com/x",
        pay_min=Decimal("45"),
        pay_max=Decimal("85"),
    )
    assert score_job(job) == 1.0  # 0.4+0.2+0.2+0.1+0.1 clamped


# --------------------------------------------------------------------------- #
# runner (end-to-end with a mock DB)
# --------------------------------------------------------------------------- #
class _FakeResult:
    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[str]:
        return []  # nothing seen before


class _FakeSession:
    """Stand-in DB: dedup finds no existing content hashes."""

    async def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        return _FakeResult()


@pytest.mark.asyncio
async def test_runner_end_to_end(sample_raw_jobs: list[RawJobSchema]) -> None:
    passing = await run_pipeline(sample_raw_jobs, _FakeSession())

    titles = [job.title for job in passing]
    # scam dropped by filter, vague dropped by threshold; survivors sorted by score desc
    assert titles == ["Entry Level Data Labeler - No Experience", "Senior Backend Engineer"]
    assert passing[0].score == pytest.approx(1.0)
    assert passing[1].score == pytest.approx(0.8)
    assert passing[0].score >= passing[1].score
