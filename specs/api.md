# Контракт API v1 (черновик для согласования)

Базовый префикс: `/api/v1`. Полная машинная спецификация — [`openapi.json`](openapi.json),
генерируется из Pydantic-схем командой `python -m app.scripts.export_openapi`.
**Это предложение, а не замороженный контракт** — меняем согласованно на первой синхронизации.

## Общие правила

- **Аутентификация:** серверная сессия, HttpOnly cookie `cc_session`. На изменяющих запросах
  (POST/PATCH/DELETE) — заголовок `X-CSRF-Token`, значение из cookie `cc_csrf` / ответа `/auth/me`.
- **Изоляция:** все данные под `/companies/{company_id}/...` доступны только членам компании.
  Чужая компания — `404` (не `403`): существование не раскрываем.
- **Деньги:** целые копейки, поля `*_minor`. Валюта MVP — RUB.
- **Единый формат ошибки:**
  ```json
  {"error": {"code": "string", "message": "строка", "field_errors": [], "request_id": "hex"}}
  ```
  `code` стабилен (на него завязывается фронт), `message` — русский текст.
- **Нереализованные ручки** отвечают `501 not_implemented` с этим же форматом.

## Ручки

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/auth/login` | Вход; ставит cookie сессии и CSRF. |
| GET | `/auth/me` | Текущий пользователь и его компании. |
| POST | `/auth/logout` | Выход (удаляет серверную сессию). |
| GET | `/companies/{id}/accounts` | Счета доступной компании, `{items:[{id,company_id,name,currency}]}`. |
| GET | `/import-presets` | Именованные mapping CSV, `{items:[{id,name,mapping}]}`; нужна сессия. |
| POST | `/companies/{id}/imports` | Загрузка выписки (multipart: `file`, `account_id`, `mapping`). Preview: ошибки строк, дубли, период. |
| POST | `/imports/{id}/commit` | Подтвердить импорт; идемпотентно, повтор не создаёт дубли. |
| GET | `/companies/{id}/transactions` | Операции; курсорная пагинация (`items`, `next_cursor`), фильтры. |
| PATCH | `/transactions/{id}/category` | Ручная правка категории (source=manual). |
| GET/POST | `/companies/{id}/planned-events` | Список и создание плановых счетов/обязательств. |
| PATCH | `/planned-events/{id}` | Правка даты/суммы/отмены планового события. |
| POST | `/companies/{id}/forecasts` | Запуск прогноза → `202` + `job_id` + `forecast_run_id`. |
| GET | `/jobs/{id}` | Статус задания: pending/running/succeeded/failed. |
| GET | `/forecasts/{id}` | Снимок прогноза: метаданные, 30+ дневных точек, риск. |
| GET | `/forecasts/{id}/explanations` | Причины риска по источникам. **501 — зона Данила/Димы.** |
| POST | `/forecasts/{id}/scenarios` | Сценарий «что если» к фиксированной базе → свой `forecast_run`. |

## Асинхронность прогноза

Прогноз считается в worker. Клиент: `POST .../forecasts` → `202` → опрос `GET /jobs/{id}` →
по `succeeded` читает `GET /forecasts/{forecast_run_id}`. WebSocket для MVP не нужен.

## Повторяемость

`forecast_run` уникален по (account, as_of, horizon, data_version, model_version, seed, scenario_hash).
Повторный запрос с теми же данными возвращает тот же прогон, а не считает заново.

## app-api-v1: согласованные дополнения

Согласование A-001/B-002: coordination/decisions/app-api-v1.md.
Список счетов сортируется по name/id, чужая компания возвращает 404.
Пресет participants-v1 предназначен для одной statements/Cxxx.csv организаторов:
UTF-8 BOM, разделитель `;`, явные русские направления. Полученный mapping передаётся
JSON-строкой в multipart импорта. Пресет не импортирует сводный all_operations.csv
в один счёт и не создаёт компании автоматически.

Минимальный UI использует cookie-сессию и CSRF из /auth/me, получает компании и счета,
показывает preview до подтверждения, курсорный список операций и 30-дневный прогноз.
Задание опрашивается до succeeded/failed, после чего загружается неизменяемый результат.
