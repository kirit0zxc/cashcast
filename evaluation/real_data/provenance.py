"""Манифест воспроизведения: хэши кода/весов и версии зависимостей без сырых данных."""

import hashlib
import platform
from importlib.metadata import version
from pathlib import Path


def manifest(weights: list[Path]) -> dict:
    return {
        "python": platform.python_version(),
        "packages": {
            name: version(name) for name in ("catboost", "numpy", "pandas", "scipy")
        },
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__file__).parent.glob("*.py"))
        },
        "weights_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in weights
        },
        "parameters": {
            "iterations": 300,
            "depth": 4,
            "learning_rate": 0.04,
            "random_seed": 20261024,
            "thread_count": 2,
        },
    }
