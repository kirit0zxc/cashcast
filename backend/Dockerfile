# Образ backend: используется и для api, и для worker (разные команды в compose).
# Версии закреплены; зависимости ставятся из uv.lock (воспроизводимо).
FROM python:3.12.15-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# uv — тем же пином, что на машинах разработки.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

WORKDIR /app

# Сначала только манифесты — слой кэшируется, пока зависимости не изменились.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Затем код приложения и миграции.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini migrate_and_seed.sh ./

# Непривилегированный пользователь.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
