"""Запуск опыта10 по предварительно зафиксированному протоколу."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.calendar_distribution import main

if __name__=='__main__':main()
