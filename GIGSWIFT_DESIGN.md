# GigSwift Agent — Complete Design Document

> Reference document for Claude Code. Read this fully before writing any code.
> Project root: `C:\GigSwift`

---

## 1. Project Summary

GigSwift Agent is a production-grade automation system that ingests remote job and gig
listings from multiple free sources, filters and scores them intelligently, generates
branded post cards, and broadcasts formatted posts to X (Twitter) and Telegram on a
scheduled interval.

It runs 24/7 on Oracle Cloud Always Free (Docker), with GitHub Actions handling CI/CD
and serving as a redundant scheduled runner. Total ongoing cost: zero.

**Tagline:** Turning fragmented gig opportunities into instant, high-signal alerts.

**Live outputs (to be linked in README once running):**
- X account: to be created
- Telegram channel: to be created

---

## 2. Goals and Non-Goals

### Goals
- Ingest from RSS feeds and Telegram channels at no cost
- Deduplicate, filter, and score listings using configurable rules
- Generate a branded Pillow image card per post
- Post to X and Telegram with proper formatting per platform
- Run reliably 24/7 on Oracle Cloud Free via Docker Compose
- Auto-deploy on every push to main via GitHub Actions
- Expose a minimal FastAPI admin interface to inspect run history
- Serve as a flagship portfolio project demonstrating production engineering

### Non-Goals (explicitly out of scope for v1)
- WhatsApp posting (no free API exists)
- LinkedIn or Google scraping (ToS violations, brittle)
- Multi-tenancy or user authentication
- Prometheus, Grafana, or any observability stack
- React or any frontend beyond FastAPI endpoints
- Temporal.io or any external orchestration system
- Paid APIs of any kind

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│              Oracle Cloud VM (Always Free)           │
│                                                      │
│  ┌─────────────────────┐   ┌──────────────────────┐ │
│  │   app container      │   │   db container        │ │
│  │                      │   │                      │ │
│  │  FastAPI (port 8000) │   │  PostgreSQL 16        │ │
│  │  APScheduler loop    │◄──►  (internal only)      │ │
│  │  Pipeline runner     │   │                      │ │
│  └─────────────────────┘   └──────────────────────┘ │
└─────────────────────────────────────────────────────┘
         ▲ deploy via SSH
         │
┌────────────────────────┐
│     GitHub Actions      │
│                         │
│  On push → main:        │
│    lint (ruff)          │
│    test (pytest)        │
│    build Docker image   │
│    push to GHCR         │
│    SSH deploy to Oracle │
│                         │
│  On cron (*/30 * * * *):│
│    redundant pipeline   │
│    run as backup only   │
└────────────────────────┘
         │
         ▼ posts to
┌──────────────┐    ┌─────────────────┐
│  X (Twitter) │    │ Telegram Channel │
└──────────────┘    └─────────────────┘
```

### Data Flow

```
RSS Feeds ──┐
            ├──► Ingestor ──► Pipeline ──► Formatter ──► Publisher
Telegram ───┘       │            │              │             │
                    │            │              │             │
                 raw jobs    filtered &      formatted     posted +
                 stored      scored jobs     posts +       logged
                             stored          images
```

---

## 4. Tech Stack

| Layer | Technology | Reason |
|---|---|---|
| Web framework | FastAPI 0.111 | Async, auto-docs, Pydantic-native |
| Scheduler | APScheduler 3.x | Runs inside app container, no extra infra |
| ORM | SQLAlchemy 2.0 (async) | Pairs with FastAPI async naturally |
| Migrations | Alembic | Schema evolution, shows production thinking |
| Database | PostgreSQL 16 | Via Docker container on Oracle VM |
| RSS ingestion | feedparser | Simple, battle-tested, zero cost |
| Telegram read | Telethon | MTProto client, reads public channels |
| X posting | tweepy 4.x | Official library, free tier write access |
| Telegram post | python-telegram-bot 21.x | Official bot library |
| Image generation | Pillow | Generates branded cards, no external API |
| Config | Pydantic BaseSettings | Validates env vars at startup, fails fast |
| Linting | ruff | Fast, replaces flake8 + black + isort |
| Testing | pytest + pytest-asyncio + httpx | Async-safe, covers FastAPI routes |
| Containerisation | Docker + Docker Compose | Two services: app + db |
| CI/CD | GitHub Actions | Lint, test, build, push GHCR, SSH deploy |
| Image registry | GHCR (GitHub Container Registry) | Free, integrated with Actions |
| Hosting | Oracle Cloud Always Free | 1 AMD vCPU, 1GB RAM, free forever |

---

## 5. Folder Structure

```
C:\GigSwift\
├── app\
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory
│   ├── scheduler.py             # APScheduler setup and pipeline trigger
│   │
│   ├── core\
│   │   ├── __init__.py
│   │   ├── config.py            # Pydantic BaseSettings, all env vars
│   │   ├── database.py          # Async SQLAlchemy engine + session factory
│   │   └── logging.py           # Structured logging config
│   │
│   ├── models\
│   │   ├── __init__.py
│   │   ├── job.py               # Job SQLAlchemy model
│   │   ├── post.py              # Post model (one per platform per job)
│   │   ├── publish_log.py       # Each publish attempt
│   │   └── run_log.py           # Each scheduler run summary
│   │
│   ├── schemas\
│   │   ├── __init__.py
│   │   ├── job.py               # Pydantic schemas for Job
│   │   ├── post.py              # Pydantic schemas for Post
│   │   └── run_log.py           # Pydantic schemas for RunLog
│   │
│   ├── ingest\
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract BaseIngestor class
│   │   ├── rss.py               # feedparser-based RSS ingestor
│   │   ├── telegram.py          # Telethon-based channel reader
│   │   └── registry.py          # Returns list of all active ingestors
│   │
│   ├── pipeline\
│   │   ├── __init__.py
│   │   ├── dedup.py             # Hash-based deduplication against DB
│   │   ├── filter.py            # Scam detection, keyword matching
│   │   ├── scorer.py            # Numeric scoring (0.0 to 1.0)
│   │   └── runner.py            # Orchestrates dedup → filter → score
│   │
│   ├── formatter\
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract BaseFormatter
│   │   ├── x_formatter.py       # X post: 280 chars, hashtags
│   │   ├── telegram_formatter.py # Telegram: Markdown, longer form
│   │   └── image.py             # Pillow card generator
│   │
│   ├── publisher\
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract BasePublisher with retry logic
│   │   ├── x_publisher.py       # tweepy client
│   │   └── telegram_publisher.py # python-telegram-bot client
│   │
│   └── api\
│       ├── __init__.py
│       ├── health.py            # GET /health
│       └── admin.py             # GET /admin/runs, /admin/errors, /admin/stats
│
├── alembic\
│   ├── env.py
│   ├── script.py.mako
│   └── versions\               # Migration files go here
│
├── tests\
│   ├── conftest.py              # Shared fixtures, test DB setup
│   ├── test_pipeline.py         # dedup, filter, scorer unit tests
│   ├── test_formatter.py        # Output format validation
│   ├── test_ingest.py           # RSS and Telegram ingestor tests (mocked)
│   └── test_api.py              # FastAPI endpoint tests via httpx
│
├── .github\
│   └── workflows\
│       └── ci.yml               # Lint → test → build → push → deploy
│
├── Dockerfile
├── docker-compose.yml
├── docker-compose.override.yml  # Local dev overrides (bind mounts, etc.)
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt         # ruff, pytest, httpx, pytest-asyncio
├── .env.example                 # All required env vars with descriptions
├── .env                         # Gitignored, real values
├── .gitignore
└── README.md
```

---

## 6. Database Schema

### Table: `jobs`
Stores every unique job listing ever seen.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | auto-generated |
| source | VARCHAR(50) | e.g. `rss:weworkremotely`, `telegram:remotejobs` |
| title | TEXT | job title |
| description | TEXT | full description |
| pay_min | NUMERIC | extracted hourly min, nullable |
| pay_max | NUMERIC | extracted hourly max, nullable |
| pay_currency | VARCHAR(10) | default USD |
| apply_url | TEXT | direct application link |
| content_hash | VARCHAR(64) | SHA256 of (title + url), used for dedup |
| score | NUMERIC | pipeline score 0.0 to 1.0 |
| is_scam | BOOLEAN | flagged by filter |
| first_seen_at | TIMESTAMP | when first ingested |
| posted_at | TIMESTAMP | when first successfully posted, nullable |

### Table: `posts`
One row per platform per job.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| job_id | UUID FK → jobs.id | |
| platform | VARCHAR(20) | `x` or `telegram` |
| content | TEXT | formatted post text |
| image_path | TEXT | local path to generated card, nullable |

### Table: `publish_log`
One row per publish attempt (success or failure).

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| post_id | UUID FK → posts.id | |
| status | VARCHAR(20) | `success`, `failed`, `retrying` |
| error_message | TEXT | nullable |
| attempt_number | INTEGER | 1-indexed |
| attempted_at | TIMESTAMP | |

### Table: `run_log`
One row per scheduler run.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| started_at | TIMESTAMP | |
| finished_at | TIMESTAMP | nullable |
| jobs_ingested | INTEGER | raw count before dedup |
| jobs_new | INTEGER | after dedup |
| jobs_posted | INTEGER | successfully published |
| errors | INTEGER | failed publishes |
| trigger | VARCHAR(20) | `scheduler` or `github_actions` |

---

## 7. Core Module Designs

### 7.1 config.py

Uses Pydantic `BaseSettings`. Reads from environment variables. Fails at startup if
required vars are missing. No silent defaults for secrets.

```python
class Settings(BaseSettings):
    # Database
    DATABASE_URL: PostgresDsn

    # X (Twitter)
    X_API_KEY: str
    X_API_SECRET: str
    X_ACCESS_TOKEN: str
    X_ACCESS_SECRET: str

    # Telegram bot (for posting)
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHANNEL_ID: str

    # Telegram client (for reading channels via Telethon)
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str

    # Pipeline tuning
    MIN_SCORE_THRESHOLD: float = 0.5
    MIN_PAY_HOURLY: float = 15.0
    SCHEDULER_INTERVAL_MINUTES: int = 30
    MAX_POSTS_PER_RUN: int = 5

    # RSS sources (comma-separated URLs)
    RSS_FEED_URLS: str

    # Telegram channels to read (comma-separated)
    TELEGRAM_CHANNELS: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

### 7.2 ingest/base.py

```python
from abc import ABC, abstractmethod
from app.schemas.job import RawJobSchema

class BaseIngestor(ABC):
    source_name: str

    @abstractmethod
    async def fetch(self) -> list[RawJobSchema]:
        """Fetch raw listings from source. Must be idempotent."""
        ...
```

### 7.3 pipeline/scorer.py

Numeric scoring. Each factor adds or subtracts from a float. Final score clamped 0.0
to 1.0. Threshold configured via `MIN_SCORE_THRESHOLD`.

```
+0.4  pay_min >= MIN_PAY_HOURLY
+0.2  pay_max present (range known)
+0.2  title contains entry-level keywords (no experience, no degree, entry level)
+0.1  description mentions remote, worldwide, work from anywhere
+0.1  apply_url present and not a redirect farm
-0.5  description contains scam flags (wire transfer, pay for training, upfront fee)
-0.3  title is all caps
-0.2  no pay information at all
```

### 7.4 formatter/image.py

Generates a 1200×630 PNG card (Twitter card dimensions) using Pillow.

Layout:
- Dark background (#0F1117)
- Top-left: GigSwift brand mark (text-based, no external font needed)
- Large: pay range in amber (#F59E0B)
- Below: job title in white, bold
- Below: platform tags (Remote, Flexible, Entry Level) as pill labels
- Bottom: subtle URL or source attribution

No external fonts. Uses Pillow's default font for v1, can upgrade to a bundled
`.ttf` in v2.

### 7.5 publisher/base.py

Retry logic lives here so all publishers inherit it.

```python
class BasePublisher(ABC):
    max_retries: int = 3
    backoff_base: float = 2.0  # seconds

    async def publish_with_retry(self, post: PostSchema) -> PublishResult:
        for attempt in range(1, self.max_retries + 1):
            try:
                result = await self.publish(post)
                await self._log(post, result, attempt, status="success")
                return result
            except Exception as e:
                wait = self.backoff_base ** attempt
                await self._log(post, None, attempt, status="failed", error=str(e))
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(wait)

    @abstractmethod
    async def publish(self, post: PostSchema) -> PublishResult:
        ...
```

### 7.6 scheduler.py

APScheduler runs `pipeline_run()` every `SCHEDULER_INTERVAL_MINUTES`. The function:

1. Creates a `run_log` entry
2. Calls `registry.get_all_ingestors()` and fetches concurrently via `asyncio.gather`
3. Passes raw jobs through `pipeline.runner.run()`
4. Formats passing jobs via all formatters
5. Publishes via all publishers
6. Updates `run_log` with final counts
7. Exits cleanly, ready for next cycle

### 7.7 api/admin.py

Three read-only endpoints. No auth for v1 (the Oracle VM is not publicly advertised;
the port can be restricted via Oracle security list to your IP if desired).

```
GET /health
    → { status: "ok", uptime_seconds: int, last_run_at: datetime }

GET /admin/runs?limit=20
    → list of RunLog records, most recent first

GET /admin/errors?limit=50
    → list of PublishLog records where status = "failed"

GET /admin/stats
    → { total_jobs_seen, total_posted, success_rate, sources_active }
```

---

## 8. Ingestion Sources (v1)

### RSS Feeds (free, no API key needed)
| Source | Feed URL |
|---|---|
| We Work Remotely | `https://weworkremotely.com/remote-jobs.rss` |
| RemoteOK | `https://remoteok.com/remote-jobs.rss` |
| Himalayas | `https://himalayas.app/jobs/rss` |
| Jobspresso | `https://jobspresso.co/feed/` |
| Remote.co | `https://remote.co/feed/` |

### Telegram Channels (public, read via Telethon, no subscription needed)
Configured via `TELEGRAM_CHANNELS` env var. Examples:
- `@remotejobshq`
- `@onlinejobskenya`
- `@remoteworkafrica`

Telethon reads the last N messages from each channel on each run, parses for job
listings, and normalises to `RawJobSchema`.

---

## 9. Post Formats

### X (Twitter) — 280 character limit
```
💰 $45–$85/hr | AI Training & Data Labeling

🕒 Remote • Flexible hours
✅ No experience required
📍 Work from anywhere

Apply → [shortened url]

#RemoteJobs #GigWork #EntryLevel #HiringNow
```

Image: 1200×630 Pillow card attached via media upload.

### Telegram — Markdown, longer form
```
📢 New Opportunity

**Role:** Content Moderation & Data Labeling
**Pay:** $25–$60/hour
**Location:** Remote (Worldwide)
**Requirements:** None — training provided

[Apply here](url)

_Posted by GigSwift Agent_
```

Image: attached as photo with caption.

---

## 10. Docker Setup

### Dockerfile
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml
```yaml
services:
  app:
    image: ghcr.io/{GITHUB_USERNAME}/gigswift:latest
    restart: always
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://gigswift:${DB_PASSWORD}@db:5432/gigswift
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    restart: always
    environment:
      POSTGRES_USER: gigswift
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: gigswift
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gigswift"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

### docker-compose.override.yml (local dev only, gitignored)
```yaml
services:
  app:
    build: .
    volumes:
      - .:/app
    environment:
      - DATABASE_URL=postgresql+asyncpg://gigswift:devpassword@db:5432/gigswift
```

---

## 11. CI/CD Pipeline

### .github/workflows/ci.yml

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '*/30 * * * *'   # redundant backup pipeline run

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install ruff
      - run: ruff check . && ruff format --check .

  test:
    needs: lint
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: gigswift
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB: gigswift_test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest --cov=app --cov-report=xml
      - uses: codecov/codecov-action@v4

  build-and-push:
    needs: test
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository_owner }}/gigswift:latest

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.ORACLE_HOST }}
          username: ${{ secrets.ORACLE_USER }}
          key: ${{ secrets.ORACLE_SSH_KEY }}
          script: |
            cd /opt/gigswift
            docker compose pull
            docker compose up -d
            docker image prune -f

  run-pipeline:
    if: github.event_name == 'schedule'
    needs: []
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt
      - run: python -m app.scheduler --once
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          X_API_KEY: ${{ secrets.X_API_KEY }}
          X_API_SECRET: ${{ secrets.X_API_SECRET }}
          X_ACCESS_TOKEN: ${{ secrets.X_ACCESS_TOKEN }}
          X_ACCESS_SECRET: ${{ secrets.X_ACCESS_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}
          TELEGRAM_API_ID: ${{ secrets.TELEGRAM_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TELEGRAM_API_HASH }}
          RSS_FEED_URLS: ${{ secrets.RSS_FEED_URLS }}
          TELEGRAM_CHANNELS: ${{ secrets.TELEGRAM_CHANNELS }}
```

Note: `--once` flag makes `scheduler.py` run the pipeline a single time and exit,
rather than starting the APScheduler loop. This is used only in the GitHub Actions
backup runner.

---

## 12. Environment Variables

All variables needed in `.env` and GitHub Secrets:

```bash
# Database (auto-set in docker-compose, override for GitHub Actions)
DATABASE_URL=postgresql+asyncpg://gigswift:yourpassword@db:5432/gigswift

# X (Twitter) — from developer.twitter.com, free tier
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_SECRET=

# Telegram Bot — from @BotFather, free
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=          # e.g. @gigswift_jobs or numeric -100xxxxxxxxxx

# Telegram Client (Telethon) — from my.telegram.org, free
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# Pipeline config
MIN_SCORE_THRESHOLD=0.5
MIN_PAY_HOURLY=15.0
SCHEDULER_INTERVAL_MINUTES=30
MAX_POSTS_PER_RUN=5

# Sources
RSS_FEED_URLS=https://weworkremotely.com/remote-jobs.rss,https://remoteok.com/remote-jobs.rss,https://himalayas.app/jobs/rss
TELEGRAM_CHANNELS=@remotejobshq,@onlinejobskenya

# Docker DB password (used in docker-compose.yml)
DB_PASSWORD=
```

---

## 13. Key Engineering Decisions (ADR Summary)

**Why APScheduler over Temporal.io:**
Temporal solves durable execution at scale across distributed workers. GigSwift has
one worker and one pipeline. APScheduler is the correct tool. Temporal would add a
Go-based server, a UI container, and weeks of setup for zero benefit at this scale.

**Why Postgres over SQLite:**
The project runs in Docker with a named volume. Postgres gives us proper async
support via asyncpg, real connection pooling, and a more honest portfolio story.
SQLite is fine for scripts; Postgres is right for a service.

**Why Pillow over external image APIs:**
Zero cost, zero rate limits, consistent branding, no external dependency. The card
design is fully controlled and can be iterated without touching any API.

**Why GHCR over Docker Hub:**
GHCR is free for public repos and integrated with GitHub Actions with no extra
credentials beyond `GITHUB_TOKEN`. Docker Hub free tier has pull rate limits.

**Why Oracle Cloud over Railway/Render:**
Railway has a credit limit. Render free tier spins down. Oracle Always Free is
genuinely always-on with no credit card charge ever. The tradeoff is a one-time
signup with card verification.

**Why read-only admin API instead of a dashboard:**
A React dashboard would add weeks of work and deliver no pipeline value. The FastAPI
admin endpoints are readable in a browser, consumable by curl, and show the same
data. A recruiter hitting `/admin/stats` is a better demo than a half-built UI.

---

## 14. README Structure (for portfolio)

```markdown
# GigSwift Agent

> Turning fragmented gig opportunities into instant, high-signal alerts.

![CI](badge) ![Docker](badge) ![Live](badge)

## What it does
## Architecture (Mermaid diagram)
## Tech decisions (ADR bullets)
## Running locally (docker compose up)
## Environment variables
## CI/CD
## Live outputs (links to X and Telegram)
## Roadmap (WhatsApp v2, scoring improvements)
```

---

## 15. Build Order for Claude Code

Follow this order strictly. Each step produces working, testable code before the next
begins. Do not skip ahead.

```
Step 1   Project scaffold
         — pyproject.toml / requirements.txt / requirements-dev.txt
         — .gitignore / .env.example
         — alembic.ini

Step 2   Core layer
         — app/core/config.py        (Pydantic BaseSettings)
         — app/core/database.py      (async SQLAlchemy engine)
         — app/core/logging.py       (structured logging)

Step 3   Models and migrations
         — app/models/ (all four models)
         — alembic/env.py
         — first migration: initial schema

Step 4   Schemas
         — app/schemas/ (Pydantic v2 schemas for all models)

Step 5   Ingestors
         — app/ingest/base.py
         — app/ingest/rss.py
         — app/ingest/telegram.py
         — app/ingest/registry.py

Step 6   Pipeline
         — app/pipeline/dedup.py
         — app/pipeline/filter.py
         — app/pipeline/scorer.py
         — app/pipeline/runner.py

Step 7   Formatter and image
         — app/formatter/base.py
         — app/formatter/x_formatter.py
         — app/formatter/telegram_formatter.py
         — app/formatter/image.py

Step 8   Publishers
         — app/publisher/base.py
         — app/publisher/x_publisher.py
         — app/publisher/telegram_publisher.py

Step 9   Scheduler
         — app/scheduler.py (APScheduler loop + --once flag)

Step 10  FastAPI app and admin API
         — app/main.py
         — app/api/health.py
         — app/api/admin.py

Step 11  Tests
         — tests/conftest.py
         — tests/test_pipeline.py
         — tests/test_formatter.py
         — tests/test_ingest.py
         — tests/test_api.py

Step 12  Docker
         — Dockerfile
         — docker-compose.yml
         — docker-compose.override.yml

Step 13  CI/CD
         — .github/workflows/ci.yml

Step 14  README
         — README.md with Mermaid diagram, badges, live links
```

---

*End of design document. Claude Code should implement each step completely before
moving to the next. All file paths are relative to `C:\GigSwift`.*
