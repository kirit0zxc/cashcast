"""Локальный запуск расширенного сравнения по протоколу journal/08_chronos_specialists.md."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.full_chronos import main

if __name__=="__main__": main()
