"""Запуск отдельного согласованного эксперимента риска."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluation.liquidity_risk.run import main
if __name__ == "__main__":
    main()
