"""Запуск протокола14: объединение разных источников предупреждений."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.complementary import main

if __name__=="__main__": main()
