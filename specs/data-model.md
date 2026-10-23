# Модель данных (раздел плана «Данные, которые нужны всем»)

Источник истины — ORM в `backend/app/core/models/`. Миграция: `backend/migrations/versions/`.
Единственный владелец миграций — backend-интегратор.

## Принципы

- **Деньги — целые копейки** (`*_minor`, BIGINT) + отдельное `direction in/out`. float запрещён.
- **Остаток дня отдельно от операций** (`daily_balance`): нельзя суммировать повторённое значение.
- **Идемпотентность входа:** уникальные ключи ловят повторную загрузку и повторный расчёт.

## Таблицы

| Таблица | Назначение | Ключевые ограничения |
|---|---|---|
| `app_user`, `user_session` | Пользователь и серверная сессия | `user_session.token_hash` — только хеш токена |
| `company`, `company_member`, `account` | Компании, доступ, счета | доступ строго через `company_member` |
| `statement_import` | Загруженный файл выписки | `uq (account_id, content_sha256)` — тот же файл не грузится дважды |
| `bank_transaction` | Фактическая операция | `uq (account_id, fingerprint)`; `amount_minor ≥ 0` |
| `daily_balance` | Остаток на конец дня | `uq (account_id, balance_date)` |
| `planned_event` | Счёт/обязательство/ручное/регулярное событие | `remaining ≤ amount`; `uq (company, source, source_ref)` |
| `planned_event_match` | Связь план↔факт (candidate/confirmed) | не допускает двойного счёта |
| `forecast_run` | Снимок прогноза | `uq` по версии входа + модель + seed + сценарий |
| `forecast_point` | Дневная точка прогноза | p10/p50/p90 + `probability_negative` (день) |
| `job` | Очередь worker | `dedupe_key` уникален; lease + повтор |

## Разделение вероятностей

- `forecast_point.probability_negative` — вероятность минуса **в этот день**.
- `forecast_run.probability_any_negative` — вероятность хотя бы одного минуса **на всём горизонте**.
- `first_negative_date` / `max_deficit_minor` — по медианной (p50) траектории.

До проверки калибровки это **модельные оценки при указанных допущениях**, не гарантия.

## CSV-импорт

Имена колонок НЕ захардкожены: задаются `column_mapping` (см. `imports/parser.py`). Реальные
имена подставим после получения датасета — схему под догадку не подгоняем.
