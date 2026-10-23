# Ночной preflight · 23 октября 2026

На эту ночь: один независимый субагент-ревьюер перед push; утром расширенное ревью
перед человеческим решением о main. Обновлены AGENTS, PROTOCOL и оба START-промпта.

## Проверено на компьютере владельца

- Docker Compose собрал web/api/worker/migrate, создал новую БД и выполнил миграции/seed.
- Локальный стенд: http://localhost:18081, project cashcast-nightcheck, loopback bind.
- Отдельный PostgreSQL test container cashcast-test-db, порт 55439, БД cashcast_test.
- Полный backend suite: 32 passed; чистые тесты не требуют PostgreSQL.
- Ruff, frontend lint/typecheck/build; Alembic check и регенерация OpenAPI без diff.
- Настоящий HTTP: login → C001.csv (1131 строк, 0 ошибок) → commit → worker succeeded
  → 30 точек baseline → повторный импорт reused. Качество модели этим не оценивалось.
- Найденные и исправленные препятствия: COPY migrate_and_seed.sh в backend image,
  направление «Поступление», зависимость unit от PostgreSQL, явный тестовый DSN.

CI результата ещё нет на момент записи: проверить текущий SHA в GitHub Actions.
CI теперь включает чистый запуск Compose, а также backend и frontend проверки.

## Что ещё предстоит агентам

- Дима принимает приглашение, получает ZIP и проверяет локальный запуск на своём ПК.
- Он fast-forward обновляет agents/b-analytics из integration/night перед стартом.
- Обмен A-001/B-001 реально между двумя ПК ещё не выполнялся; не имитировать ACK.
- Доработать продукт: UI ещё health-страница, модель baseline, категории/планирование
  — заглушки. Для UI нужен способ получить account_id через согласованный API:
  текущий smoke получил ID демосчёта напрямую из локальной БД, это не готовый UX.
- npm audit сообщил 4 advisory (2 low, 1 moderate, 1 high) в исходном dependency tree.
  Не выполнять audit fix --force вслепую; отдельная проверка зависимостей до публикации.
- Работа запускается двумя активными задачами; монитор/автоперезапуск не настроен.
