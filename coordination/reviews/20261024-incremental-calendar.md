# Приёмка частичного календаря — 24.10.2026

Код: f1e1490f01db4ace9ec2ad637b32a9ef5d325edc.
Проверенное дерево: b202ffdcd9be768d27f65845123c325de2d45a8a.
База main: 0a4d3bc7e0194815c30a5adfb8dbe2c3a5813c22.
Следующий commit добавляет только этот отчёт.

## Автор

- Полный backend: 611 passed / 110.21s на отдельной PostgreSQL cashcast_test:55439.
- После добавления двух cross-account/company регрессий профильный файл: 3 passed / 2.87s.
  Итого проверены 613 различных backend-тестов; второй полный прогон не заявляется.
- Ruff app/tests и export OpenAPI: passed, 23 paths, nullable CalculationOut.
- Frontend: 15 unit, eslint, tsc/build passed; прежнее предупреждение размера JS chunk.
- Docker cashcast-pr49-main / localhost:18093: успешная сборка и миграции.
- Все 11 Chromium E2E без моков passed / 46.0s.
- После реального restart worker: incremental.spec.ts passed / 4.8s.
- Старые стенды 18086/18091 не изменены, volumes не удалены.

## Независимое ревью

- cashcast_bootstrap_a: READY точного commit/tree. API/tenant/frozen/UI проверены,
  20 независимых full-vs-legacy probes и partial probes совпали. Предложенные
  repository isolation tests добавлены и пройдены.
- cashcast_bootstrap_final: READY того же commit/tree. Независимые 60 сравнений full
  с legacy и 240 цепочек incremental/full после JSON roundtrip совпали до копейки.
  Границы горизонта, короткая история, несверка EOD, регулярности и оплаты покрыты.
- cashcast_bootstrap_b: третий verifier READY того же commit/tree по коду, документам
  и проверке доказательств. Его дополнительный runtime probe не запустился из-за
  недоступного интерпретатора Python312; собственных runtime-результатов verifier не заявлял.

Блокеров не найдено. Это частичный календарный пересчёт: новые банковские факты
по-прежнему требуют full, online-обучение не заявляется. Валидация/сбор снимка остаются.
GitHub Actions не заявляется зелёным: skip ci по согласованной квоте, проверки локальные.
Merge/Approve — человеку. Проверка пользователя: docs/check-incremental-forecast.md.
