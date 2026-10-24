"""Запуск плавных весов по заранее зафиксированному протоколу12."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.horizon_ensemble import main

if __name__=='__main__':main()
