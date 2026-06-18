# ---------------------------------------------------------------------------
# Builder stage: install dependencies into an isolated virtualenv.
# Build tools live here only; they are not carried into the final image.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Final stage: copy only the prepared virtualenv and the application code.
# (asyncpg/Pillow/pydantic-core ship self-contained wheels, so no runtime
# system libraries are needed here.)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS final

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Telethon session file lives here. Mount a volume to persist it across deploys.
RUN mkdir -p /app/data

# Application code, Alembic config, and migrations. Versions are baked in so the
# deploy step can run `alembic upgrade head` before the app starts.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
