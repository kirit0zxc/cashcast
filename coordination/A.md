# Статус A

state: WORKING
task: A0/A1; пробный обмен и минимальный UI
code_sha: d444361af2906f4a1614004760d23dd4014a2b3b
tested_sha: d444361af2906f4a1614004760d23dd4014a2b3b
last_update: 2026-10-23T20:23:16Z
contract_version: archive-v1 (нужен аудит)

## Следующее действие
Прочитать AGENTS.md и PROTOCOL; проверить GitHub и тестовую БД, согласовать B0.

## A-001 · CHECK-IN / предложение app-api-v1

UTC: 2026-10-23T20:23:16Z
reply_to: none
task: A0/A1
type: proposal
base_sha: d444361af2906f4a1614004760d23dd4014a2b3b
contract_version: app-api-v1 (предложение, ACK ожидается)
ETA: следующий heartbeat не позднее 2026-10-23T20:43:16Z

Агент A запущен. Собственное дерево чистое; Docker API/worker/web/Postgres и выделенная
тестовая БД работают. Предыдущий полный suite 32 passed, CI bootstrap зелёный.
Прошу B подтвердить доступ, DTO archive-v1 и прислать небольшой проверенный B0-пакет
для полного пробного цикла. На обоих ПК обмен ещё не подтверждён.

Предлагаю аддитивный app-api-v1 (только HTTP, без изменения аналитических DTO):
- GET /api/v1/companies/{company_id}/accounts → {items:[{id,company_id,name,currency}]}.
  Только член компании; чужая компания 404; ID строки UUID, порядок name/id.
- GET /api/v1/import-presets → {items:[{id:"participants-v1",name,mapping}]}.
  Нужна сессия. mapping: date="operation_date", amount="amount", direction="direction", counterparty_name="counterparty_name",
  counterparty_ref=counterparty_inn, purpose=payment_purpose, external_id=operation_id,
  balance=balance_eod, delimiter=";", encoding="utf-8-sig"; inflow/outflow/currency=null.
  Внутренние direction_in_values/default_currency сохраняют defaults, в HTTP их не добавляем.
  Не создаём автоматом все компании по all_operations: загружаем одну statements/Cxxx.csv
  в явно выбранный счёт. Сырой датасет в репозиторий не идёт.
До ACK реализую независимый минимальный UI по существующему API и тесты окружения;
новые HTTP-контракты не считаю утверждёнными. Прошу ACK app-api-v1 или конкретные правки.

## Сообщения
## A-INFO-DATASET-001 · вводные владельца 23.10.2026

type: information; ACK от B ожидается; продуктовые агенты ещё не запущены.
Получен датасет: 150 компаний, 222420 операций. Прочитать
specs/dataset-participants.md на origin/agents/a-app. ZIP получить отдельно.
Ночью frontend минимальный, утром будет переработан. Приоритет — backend/аналитика.
Журналы попыток добавлены в coordination/attempts; B после принятия пакета владеет B.md.
Это изменение плана по прямому указанию владельца, не изменение публичного API.

## A-INFO-PREFLIGHT-001

Владелец разрешил на ночь одного ревьюера. Обновлены AGENTS и START-A/START-B.
Локальный запуск и 30 backend-тестов прошли, полный результат в PREFLIGHT.md.
B должен получить финальную integration/night перед запуском. Не считать эту запись
ответом B или доказательством проверки компьютера Димы. CI проверяется отдельно.
