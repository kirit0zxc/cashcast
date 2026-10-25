"""Только чистые исследовательские unit-тесты: без приложения, сети и БД."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
paths=[*ROOT.joinpath('evaluation/fallback_model').glob('test_*.py'),*ROOT.joinpath('evaluation/liquidity_risk').glob('test_*.py')]
names=['.'.join(p.relative_to(ROOT).with_suffix('').parts) for p in sorted(paths)]
result=unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))
raise SystemExit(0 if result.wasSuccessful() else 1)
