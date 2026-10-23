"""Выгрузка OpenAPI в specs/openapi.json. Запуск: `python -m app.scripts.export_openapi`.

Контракт v1 генерируется FastAPI из Pydantic-схем — один источник истины для фронта и тестов.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

# backend/app/scripts/export_openapi.py -> корень репозитория на три уровня выше backend.
OUT = Path(__file__).resolve().parents[3] / "specs" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"openapi -> {OUT} (paths: {len(schema.get('paths', {}))})")


if __name__ == "__main__":
    main()
