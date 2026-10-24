"""Entrypoint worker: `python -m app.worker`. Тот же образ, что API, другая команда."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.logging import configure_logging
from app.modules.jobs.worker import run_forever


def main() -> None:  # pragma: no cover — запускается в контейнере
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        run_forever(factory)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
