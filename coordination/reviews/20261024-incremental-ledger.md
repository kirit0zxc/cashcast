# Ledger incremental v2 — итог проверки 24.10.2026

Code commit: 4a15cd17b45c9ae0bc4bf3270f89c94be3c1f60a.
Reviewed tree: b0726d8d5b8215994f06e2536608203790caa182.
Base main: 0a4d3bc7e0194815c30a5adfb8dbe2c3a5813c22. PR #50.

## Проверки автора

- Полный backend: 636 passed, отдельная cashcast_test PostgreSQL, 128.77 s.
- После последнего fingerprint guard: 40 pure incremental tests passed, Ruff clean.
  Полный suite был до этой небольшой финальной проверки служебного checkpoint.
- Frontend: 15 unit, lint, build; известное предупреждение о chunk >500 kB.
- Отдельный Docker cashcast-ledger-review, localhost:18094: 12 Chromium E2E passed.
- Финальный rebuild с guard, restart worker: оба incremental E2E повторно passed.
- Реальный CSV, сохранение результата, повтор без дублей, tenant/account isolation.
- OpenAPI экспорт обновлён; diff --check чист; ключи/сырые выписки не добавлялись.

## Независимые ревью

- cashcast_bootstrap_a: 80 последовательных сравнений с frozen oracle; обнаружил
  malformed context и отсутствующий fingerprint. Оба исправлены; 7 повреждённых
  вариантов дали точный full fallback, валидный checkpoint остаётся incremental. READY.
- cashcast_bootstrap_final: 192 независимых сравнения с legacy; дополнительные 15
  malformed вариантов дали full. Математические blobs неизменны после сравнений.
  Старое описание v1 в README и лишние EOF исправлены. READY по коду.
- cashcast_bootstrap_b: третий верификатор проверил итоговый tree выше, исправления,
  изоляцию, дельту, bootstrap, лимиты и документацию. READY, blockers нет.
  Рецензенты не запускали общую БД; результаты runtime выше получены автором.

## Границы

Частично обновляется вычислительное состояние worker. API продолжает читать и
проверять полный снимок. Первый/несовместимый/старый/повреждённый checkpoint,
смена горизонта/seed/модели и сценарии используют full. Это не online-обучение.
Количество новых траекторий иногда 200 и в частичном режиме при смене сетки.

Локальные проверки подтверждены; GitHub Actions не выдаются за зелёные:
согласованный режим экономии квоты [skip ci]. Main сливает человек.
OpenRouter-ассистент в этот PR не входит; пока только обсуждение.
