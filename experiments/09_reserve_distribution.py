"""Запуск локального опыта09 с замороженным временным разбиением."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.distribution_run import main

if __name__=='__main__': main()
