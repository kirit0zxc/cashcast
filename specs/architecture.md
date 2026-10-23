# Архитектура (модульный монолит)

```
Браузер (React/TS)
      │  /api  (cookie-сессия)
      ▼
nginx  ──►  FastAPI (api)        PostgreSQL
                │  ставит job        ▲
                ▼                     │ очередь + lease
             worker  ────────────────┘
          (тот же образ, другая команда)
```

- **Один образ backend** для `api` и `worker` — разные команды запуска.
- **Очередь в PostgreSQL**: `SELECT … FOR UPDATE SKIP LOCKED` + lease/повтор. Без брокеров.
- **Публичный сервис один** — `web` (nginx). `api`, `worker`, `postgres` во внутренней сети.
- **Снимок прогноза неизменяем**: сценарии считаются от зафиксированной базы тем же расчётом.

## Пакеты backend

```
app/core/        настройки, БД, ошибки, сессии, request_id, модели
app/modules/
  imports/       разбор CSV (настраиваемый маппинг), preview, commit
  categorization/ категории (заглушка → Дима)
  planning/      регулярности и план-факт (заглушки → Дима)
  forecasting/   baseline + снимок данных (финальная модель → Данил)
  jobs/          очередь и worker
app/api/         тонкие HTTP-обработчики и Pydantic-схемы
evaluation/      backtest и отчёты (Данил)
```

## Границы владения

| Папка | Владелец |
|---|---|
| `frontend/` | Диана |
| `backend/` (ядро, api, imports, jobs, инфра, миграции) | Интегратор |
| `modules/forecasting/`, `evaluation/` | Данил |
| `modules/categorization/`, `modules/planning/` | Дима |

Контракт между интегратором и аналитикой — `backend/app/modules/contracts.py`
(чистые DTO, без HTTP и ORM). Данил и Дима реализуют Protocol-интерфейсы внутри своих папок.
