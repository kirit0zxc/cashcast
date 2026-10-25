"""Повторяемая локальная политика чувствительных предупреждений."""
import runpy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if __name__=="__main__":
    runpy.run_module("evaluation.liquidity_risk.policy",run_name="__main__")
