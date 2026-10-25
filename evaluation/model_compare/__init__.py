"""Сравнение текущих и новых моделей; продуктовый реестр не меняется."""

import sys
from pathlib import Path

# Всем модулям пакета нужен backend/app: реестр моделей и метрики «Проверки качества».
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
