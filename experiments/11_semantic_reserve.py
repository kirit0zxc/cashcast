"""Запуск опыта11 по протоколу семантики прошлых платежей."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.semantic_distribution import main

if __name__=='__main__':main()
