"""Воспроизводимый запуск обучения13; оценка выполняется отдельной командой."""
import runpy
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    runpy.run_module("evaluation.liquidity_risk.finetune",run_name="__main__")
