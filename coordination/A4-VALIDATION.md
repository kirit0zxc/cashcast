# A4: локальная приёмка 24.10.2026

Продуктовый код:5d80b71166b30e93344e7bb353d109a43ebed972. Все3jobs CI40026907533
success: backend, frontend, Clean Docker startup+Chromium E2E. Локально93backendtests
на cashcast_test, Ruff, frontend lint/typecheck/build, независимое ревью A3.

Создан отдельный cashcast-fresh-demo с новым volume cashcast-fresh-demo_pgdata,
web127.0.0.1:18083. Прежние HoneyForge и cashcast-nightcheck не изменялись.
WEB_PORT=18083, docker compose -p cashcast-fresh-demo -f infra/docker-compose.yml
up -d --build: migrate exit0, API/worker/web/PostgreSQL работают.

Ручная приёмка из backend:

```text
.venv/Scripts/python.exe -m app.scripts.smoke_demo --base-url http://127.0.0.1:18083 --zip ../data/raw/cashflow_dataset_participants.zip --write-demo-data
```

PASS: C0011131строка, preview0ошибок; полная пагинация без повторных ID. Повтор commit
возвращает сохранённую статистику, набор ID не меняется. Настоящий worker:30точек,
explanations с источниками. Создан тестовый план, plan-fact его видит.
Все4APIсценария успешны: expense−100000копеек; delay+123456на прежнюю дату и0после
новой; reduce/increase меняют результат. Базовые points не изменились. Logout→me401.
Историческая база2026-09-30 содержит3регулярности; текущая их не подтверждает,
поэтому increase проверен на исторической базе, новый план/перенос — на текущей.
Каждый запуск добавлял отдельный демо-план.

Исправлялись проверки самого smoke, не продукт: повтор commit отдаёт первоначальный
inserted, logout204без JSON, текущая C001не даёт целей increase. Повтор обоснован
исправлением клиента/выбором среза с реальными обнаруженными регулярностями.

После compose restart postgres/api/worker/web:1131bank_transaction/14forecast_run/
420forecast_point до/после одинаковы. pg_dump-Fc и pg_restore в новую отдельную
cashcast_restore_check дали те же1131/14/420. Рабочая БД не очищалась/не перезаписывалась.

## Матрица перед расширенной ночью

| Требование | Состояние и доказательство |
|---|---|
| Выписка/дубли/категории | Реализовано; API regression и C001smoke; ручная категория API |
| Регулярности | Эвристики проверены, C001историческая база; B5–B10 расширяют крайние случаи |
| Прогноз30+дней | API1–180, UI30; E2E/smoke; backtest только30дней |
| Риск/причины | Реализовано; качество вероятностей не подтверждено, B6 в очереди |
| План/источник | Ручной API есть; CSV обязательств отсутствует |
| План-факт | Auto/residual/concurrency есть; ручное подтверждение кандидатов отсутствует |
| Четыре сценария/сравнение | Реальный API/worker проверен; UI только дополнительный расход |
| Дополнительные источники | Ручные подтверждённые суммы/даты; файловый импорт предстоит |
| Восстановление | Restart/dump/restore проверены; далее аудит lease/retry |
| Доступ/CSRF | Изоляция/CSRF покрыты; далее IDs/ресурсы/параллелизм |
| Утренний frontend | Минимальный реальный UI есть; визуальная переработка отдельно |

Это A4 checkpoint, не завершение расширенной цели до09:00. Приёмка не доказывает
калибровку риска, production-нагрузку или внешние банковские интеграции. Стенд локальный.
