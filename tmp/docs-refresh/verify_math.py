"""Проверка чисел документа на неизменённой модели из снимка Git; без БД."""
import ast
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

root = Path(__file__).resolve().parent
backend = root / 'source-60147f0/backend'
sys.path.insert(0, str(backend))
# Из оригинальной регрессии берём только импорты чистой модели и demo-fixture.
# FrozenPulseService требует FastAPI, отсутствующий в runtime документов.
source = ast.parse((backend / 'tests/analytics/test_cutoff_gap.py').read_text(encoding='utf-8'))
nodes = [n for n in source.body if
         isinstance(n, (ast.Import, ast.ImportFrom)) and getattr(n, 'module', '') != 'app.modules.pulse.frozen'
         or isinstance(n, ast.FunctionDef) and n.name == 'demo']
scope = {}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<original-demo-fixture>', 'exec'), scope)
from app.modules.contracts import PlannedEventDTO, Direction
from app.modules.forecasting.service import get_forecast_service

data = scope['demo']()
service = get_forecast_service()
result = service.run(data)
assert result.model_version == 'seasonal-estimated-2.1-w84'
assert len(data.txns) == result.details['quality']['history_days'] == 6
assert data.opening_balance_minor == 26_040_000
assert min(p.balance_p50_minor for p in result.points) == 24_790_000
assert result.points[-1].balance_p50_minor == 28_950_000
assert result.risk.first_negative_date is None
assert result.risk.probability_any_negative is None
payment = PlannedEventDTO('large', Direction.OUT, 40_000_000, 40_000_000,
                         date(2026,8,3), 'planned', 'manual', 'manual', data.as_of)
known = service.run(replace(data, planned_events=[payment]))
assert known.risk.first_negative_date == date(2026,8,3)
assert known.risk.max_deficit_minor > 0
assert known.risk.probability_any_negative is None
later = service.run(replace(data, planned_events=[replace(payment, available_at=date(2026,10,24))]))
assert later.points == result.points
middle = service.run(scope['demo'](date(2026,9,1)))
assert middle.details['quality']['eligible_for_simulation']
assert not middle.details['quality']['eligible_for_probability']
assert middle.risk.probability_any_negative is None
long = service.run(scope['demo'](date(2026,10,24)))
assert long.risk.probability_any_negative is not None
out = {
 'source_commit':'60147f01e4627c0f065170cc02ab451219b3020f',
 'fixture':'backend/tests/analytics/test_cutoff_gap.py::demo',
 'checks_passed':5,
 'scope':'direct pure forecast calculations, no pytest or Pulse/API/DB runtime',
 'short':{'as_of':str(data.as_of),'history_days':6,'opening_minor':data.opening_balance_minor,
          'minimum_p50_minor':min(p.balance_p50_minor for p in result.points),
          'end_p50_minor':result.points[-1].balance_p50_minor,'probability':None},
 'known_expense':{'amount_minor':40_000_000,'first_negative':str(known.risk.first_negative_date),
                  'max_deficit_minor':known.risk.max_deficit_minor},
 'later_plan_ignored':True,
 'middle_history':middle.details['quality'],
 'long_probability':long.risk.probability_any_negative,
}
(root/'math-verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=True,indent=2))
