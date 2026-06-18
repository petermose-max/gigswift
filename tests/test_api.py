"""Tests for the FastAPI health and admin endpoints (via httpx).

DB-backed assertions run on SQLite. SQLite stores datetimes timezone-naive, so the
``RunLogSchema.status`` tz comparison (``started_at > datetime.now(UTC)``) only runs
for *unfinished* rows — which production (Postgres, tz-aware) never has a problem
with. We therefore seed only *finished* runs through the API and verify the full
running/interrupted/completed logic separately in ``test_runlog_status_states``
with tz-aware datetimes constructed in Python.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Job, Post, PublishLog, RunLog
from app.schemas.run_log import RunLogSchema


@pytest.fixture
async def seeded(sessionmaker_: async_sessionmaker) -> None:
    """Seed finished runs, jobs, posts, and publish logs; session closed before requests."""
    now = datetime.now(UTC)
    async with sessionmaker_() as s:
        s.add_all(
            [
                RunLog(
                    trigger="scheduler",
                    started_at=now - timedelta(hours=1),
                    finished_at=now - timedelta(minutes=59),
                ),
                RunLog(
                    trigger="github_actions",
                    started_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=4),
                ),
            ]
        )
        posted = Job(
            source="rss:weworkremotely",
            title="Posted Job",
            description="d",
            apply_url="https://e/1",
            content_hash=uuid.uuid4().hex,
            pay_currency="USD",
            is_scam=False,
            posted_at=now,
        )
        unposted = Job(
            source="telegram:remotejobs",
            title="Unposted Job",
            description="d",
            apply_url="https://e/2",
            content_hash=uuid.uuid4().hex,
            pay_currency="USD",
            is_scam=False,
        )
        s.add_all([posted, unposted])
        await s.flush()

        post = Post(job_id=posted.id, platform="x", content="c", image_path=None)
        s.add(post)
        await s.flush()
        s.add_all(
            [
                PublishLog(post_id=post.id, status="success", attempt_number=2),
                PublishLog(
                    post_id=post.id, status="failed", attempt_number=1, error_message="boom"
                ),
            ]
        )
        await s.commit()


def test_runlog_status_states() -> None:
    """The derived status field: completed / running / interrupted (tz-aware inputs)."""
    now = datetime.now(UTC)

    def _schema(started: datetime, finished: datetime | None) -> RunLogSchema:
        return RunLogSchema(
            id=uuid.uuid4(), trigger="scheduler", started_at=started, finished_at=finished
        )

    assert _schema(now - timedelta(hours=1), now).status == "completed"
    assert _schema(now - timedelta(minutes=1), None).status == "running"
    assert _schema(now - timedelta(minutes=30), None).status == "interrupted"


@pytest.mark.asyncio
async def test_health(client: AsyncClient, seeded: None) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["last_run_at"] is not None
    assert body["uptime_seconds"] == 0  # lifespan not started via ASGITransport


@pytest.mark.asyncio
async def test_admin_runs_newest_first_with_status(client: AsyncClient, seeded: None) -> None:
    resp = await client.get("/admin/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 2
    assert all("status" in run for run in runs)  # derived field present
    assert [run["status"] for run in runs] == ["completed", "completed"]
    # newest first by started_at (github_actions run started more recently)
    assert runs[0]["trigger"] == "github_actions"
    assert runs[1]["trigger"] == "scheduler"


@pytest.mark.asyncio
async def test_admin_runs_limit_validation(client: AsyncClient, seeded: None) -> None:
    assert len((await client.get("/admin/runs?limit=1")).json()) == 1
    assert (await client.get("/admin/runs?limit=101")).status_code == 422  # capped at 100
    assert (await client.get("/admin/runs?limit=0")).status_code == 422
    assert (await client.get("/admin/runs?limit=100")).status_code == 200


@pytest.mark.asyncio
async def test_admin_errors_only_failed(client: AsyncClient, seeded: None) -> None:
    resp = await client.get("/admin/errors")
    assert resp.status_code == 200
    errors = resp.json()
    assert len(errors) == 1
    assert errors[0]["status"] == "failed"
    assert errors[0]["error_message"] == "boom"


@pytest.mark.asyncio
async def test_admin_stats(client: AsyncClient, seeded: None) -> None:
    resp = await client.get("/admin/stats")
    assert resp.status_code == 200
    assert resp.json() == {
        "total_jobs_seen": 2,
        "total_posted": 1,
        "success_rate": 0.5,
        "sources_active": 2,
    }
