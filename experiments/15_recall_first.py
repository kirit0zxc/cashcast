"""Запуск протокола15 с приоритетом дополнительных обнаруженных разрывов."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.recall_first import main
if __name__=='__main__':main()
