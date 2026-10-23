"""Настройка логов. Правило проекта: назначения платежей, реквизиты, токены и файлы в лог не пишем."""

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # SQL-эхо выключено намеренно: в параметрах запросов лежат назначения платежей.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
