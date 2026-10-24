"""Локальный запуск внешней модели временных рядов."""
import sys,runpy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=="__main__":
    runpy.run_module("evaluation.liquidity_risk.chronos_trial",run_name="__main__")
