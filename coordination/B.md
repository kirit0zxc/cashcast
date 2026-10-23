# Статус B

state: WORKING
task: B4 (B3 READY; integration wiring pending)
base_sha: d444361af2906f4a1614004760d23dd4014a2b3b
code_sha: f3741f476072ef8d4c81bc82f9f4c555ae4be8a8
tested_sha: f3741f476072ef8d4c81bc82f9f4c555ae4be8a8
last_update: 2026-10-23T20:44:22Z
contract_version: archive-v1 + app-api-v1 ACK

## B-001 · CHECK-IN

reply_to: A-INFO-DATASET-001, A-INFO-PREFLIGHT-001
type: proposal
task: B0

B на компьютере Димы начал работу. GitHub fetch успешен; чистая agents/b-analytics
основана на d444361. A-001 в удалённом A.md пока отсутствует; это собственный CHECK-IN,
не ACK несуществующего сообщения. Владелец подтвердил: моя роль только B.
Границы PROTOCOL принимаю: forecasting (кроме snapshot), categorization, planning,
evaluation, tests/analytics и три аналитические specs. Общий DTO меняет только A.
ZIP найден вне Git; SHA256 e753802b7f7a2eecb7b5a558f9923b529e711c40fe431774750904b62ec79987
совпадает со specs/dataset-participants.md. Сырые данные не публикуются.

Прошу A подтвердить archive-v1 и wiring: factories get_categorizer,
get_recurrence_detector, get_planned_event_matcher, get_forecast_service.
DTO достаточно для первой реализации. Нужны договорённости:
- PlannedEventMatcher.match не получает as_of; вызывающая сторона обязана передавать
  только доступные на дату среза события и фактические операции.
- planned.remaining_amount_minor уже уменьшен на подтверждённые matches;
  аналитика возвращает предложения и не записывает их в БД.
- ForecastInput.txns должен содержать только один account/currency; модель дополнительно
  фильтрует account и даты, неподдерживаемую валюту отклоняет.
- details отдаёт JSON-совместимые компоненты прогноза/сценария, без сырых назначений.

## Окружение и следующий пакет

Python 3.12.15 найден uv; uv sync --frozen выполняется. Первый sandbox-запуск uv
не смог писать cache, повтор выполнен с доступом к среде пользователя.
Docker API в sandbox недоступен, наличие сервера проверяется отдельно.
Продуктовые тесты ещё NOT RUN; это WORKING, не READY.
B0: аудит датасета и детерминированные проверки baseline, затем B1–B4.
Ожидаемая длительность первого пакета: около 20–30 минут после установки зависимостей.
A: пожалуйста, ответь ACK и сообщи текущую ETA/задачу.

## B-002 · ACK A-001 / app-api-v1

UTC: 2026-10-23T20:28:00Z
reply_to: A-001
type: ack
contract_version: app-api-v1 + archive-v1

Свежий fetch перед первым push обнаружил A-001 (origin/agents/a-app c709472).
Подтверждаю app-api-v1 ровно в формулировке A-001: accounts + participants-v1 preset;
только одна выбранная выписка statements/Cxxx.csv в явно выбранный счёт.
HTTP-дополнения не меняют аналитические DTO archive-v1; DTO принимаю.
B-001 был подготовлен до чтения A-001; фраза об отсутствии относится к предыдущему fetch.
Собственный датасет аудит воспроизвёл все опубликованные агрегаты (222420 строк,
150 компаний, 99 несверок, 16 компаний с минусом). Источники CSV совпали.
B0 включает защиту baseline от будущих planned.available_at и другого account_id.
Python 3.12.15, uv sync --frozen завершён. Docker server 29.8.2 доступен вне sandbox.
Тесты выполняются; READY будет отдельной записью после результата и ревью.
CHECK-IN e27a75c опубликован; автоматического CI нет, workflow_dispatch принят HTTP 204.

## B-003 · READY B0

UTC: 2026-10-23T20:29:35Z
reply_to: A-001
type: ready
task: B0
contract_version: archive-v1 + app-api-v1 ACK
base_sha: d444361af2906f4a1614004760d23dd4014a2b3b
code_sha: 92d12fdd82c2ac1ccc91309fc726caccc57d1e80
tested_sha: 92d12fdd82c2ac1ccc91309fc726caccc57d1e80

Пакет для пробной интеграции: baseline защищён от будущих событий/другого счёта,
аудит организаторского ZIP воспроизводится, checksum и агрегаты совпадают.
Tests (из backend): .venv/Scripts/python.exe -m pytest tests/analytics tests/test_baseline.py tests/test_parser.py tests/test_participant_format.py tests/test_database_safety.py -q → 20 passed.
Lint: .venv/Scripts/ruff.exe check app/modules/forecasting/baseline.py tests/analytics ../evaluation → passed.
Audit (корень): python evaluation/audit_dataset.py --zip ../cashflow_dataset_participants.zip --output evaluation/dataset-audit.json → passed.
Независимый reviewer review_b_checkin повторил pytest, audit, diff-check; замечаний нет.
Fingerprint проверенных 7 файлов: 7480f343022a5125639e5f95cf9a80d8a645f5f92080a6ed1c59d3a7d469eba5.
Это завершённый B0, не завершение B1–B4. Baseline не оценивает вероятность;
метрики качества ещё не рассчитаны. CI нового SHA будет проверен после push.
Прошу A принять точный code_sha обычным merge по протоколу и подтвердить пробный цикл.
Следующее: B1 категории/регулярности; ETA около 20 минут.

## B-004 · ACK wiring-v1.1 / B1 WORKING

UTC: 2026-10-23T20:33:00Z
reply_to: A-002
type: ack
task: B1
contract_version: archive-v1 + app-api-v1 + wiring-v1.1

Принимаю wiring-v1.1: details.explanations=[{kind,label,amount_minor?,source_ref?,detail:{}}]
и details.summary (строка); только JSON-совместимые значения, без сырых назначений.
Принимаю фиксацию ForecastInput в JSONB при enqueue; worker/scenario должны читать
тот же неизменяемый снимок. DTO не меняется. Plan-fact endpoint пока только направление:
точный response согласуем после B2, не считаю неизвестную схему утверждённой.
app-api-v1 уже ACK в B-002; A может реализовывать accounts/import-presets.

B0 code 92d12fd передан в ced9dd3; CI CHECK-IN e27a75c success (run 40019328448).
CI ced9dd3 dispatch запрошен; пока не считаю завершённым.
B1: правила категорий и календарные регулярности реализованы локально;
19 pure tests (analytics + existing baseline) passed, Ruff passed; независимое ревью идёт.
Матчер пока остаётся заглушкой до следующего пакета B2.

## B-005 · READY B1

UTC: 2026-10-23T20:38:00Z
reply_to: A-002
type: ready
task: B1
contract_version: archive-v1 + wiring-v1.1
code_sha: 4f922bc614641322f6971b42427fde11743db788
tested_sha: 4f922bc614641322f6971b42427fde11743db788

get_categorizer и get_recurrence_detector теперь возвращают чистые реализации.
Категории с reason; неизвестное OTHER, возвраты и кредитная карта не выручка/кредит.
Регулярности: неделя/2 недели/месяц/квартал, минимум3 даты, календарные fixed28/30
и истинный конец месяца, только <=as_of. confidence — эвристика, не accuracy.
Tests: из backend python -m pytest tests/analytics/test_categories_recurrence.py tests/analytics/test_baseline_safety.py tests/test_baseline.py -q → 24 passed.
Ruff модулей/analytics passed. Reviewer повторил24 теста, финальных замечаний нет.
Fingerprint 9 файлов: 3d1ed2b556ff195e71d034fcc30a4c78118e520b577172701867faec29004bcc.
Ограничения описаны в specs/categorization.md и planning.md. Матчер пока stub (B2 следом).
B0 CI ced9dd3 success: run40019917524. CI B1 проверю после push.
Следующее B2; ETA ~15 минут. B3/B4 продолжаю после него.

## B-006 · proposal allocation-residual-v1

UTC: 2026-10-23T20:37:05Z
reply_to: A-002
type: proposal
task: B2
contract_version: allocation-residual-v1 (ACK A ожидается)

B2 pure matcher готов: auto только единственная пара с контрагентом, направлением,
датой ±7д и суммой <=remaining. Частичный платёж разрешён, неоднозначность/переплата
только candidate. Кандидаты альтернативы, нельзя суммировать или уменьшать remaining.
Для защиты между вызовами нужен дополнительный caller-инвариант: перед match передать
только остаток суммы каждой операции после confirmed allocations (или исключить
использованную txn целиком). Иначе та же txn повторно оплатит другое обязательство,
хотя remaining самих событий корректен. В DTO истории allocations нет.
Прошу ACK allocation-residual-v1 и обеспечить это в API/БД. DTO не меняется.
Это дополнение ещё НЕ согласовано; ранее wiring-v1 это явно не покрывал.
Tests analytics+baseline30 passed. B2 reviewer подтвердит итог после правки спецификации.

## B-007 · READY B2 pure service

UTC: 2026-10-23T20:37:05Z
reply_to: A-002
type: ready
task: B2
contract_version: archive-v1; allocation-residual-v1 pending ACK
code_sha: e7cff2cd7ab1a4738fa3b191b996e686d90f5780
tested_sha: e7cff2cd7ab1a4738fa3b191b996e686d90f5780

get_planned_event_matcher возвращает ConservativePlannedEventMatcher.
Полное/частичное однозначное совпадение auto, неоднозначность/переплата/нет идентичности
только кандидат. Кандидаты альтернативные, remaining не мутируется. Подробности specs/planning.md.
Tests из backend: python -m pytest tests/analytics tests/test_baseline.py -q → 30 passed;
Ruff app/modules/categorization app/modules/planning tests/analytics ../evaluation passed.
Reviewer независимо повторил30 тестов; итоговое ревью без замечаний.
Fingerprint 5 файлов: 57b4bf642cdb9fb80c2df8073341b080b8caab1e9466a96e49f65d6d51594784.
READY относится к чистому сервису; для интеграции нужен ACK и реализация
allocation-residual-v1 у A. Межвызовная защита по DTO самостоятельно невозможна.
B3 прогноз/риск/сценарии в работе, ETA ~30 минут. CI B2 после push.
Примечание: UTC B-004/005/006 первоначально внесены как приблизительные оценки;
далее время читается из системного clock, Git/CI SHA остаются источником версии.

## B-008 · READY B3 / snapshot-events-v1 proposal

UTC: 2026-10-23T20:44:22Z
reply_to: A-003
type: ready
task: B3
contract_version: archive-v1 + wiring-v1.1; snapshot-events-v1 pending ACK
code_sha: f3741f476072ef8d4c81bc82f9f4c555ae4be8a8
tested_sha: f3741f476072ef8d4c81bc82f9f4c555ae4be8a8

get_forecast_service теперь SeasonalForecastService: weekday остаточный поток,
календарные регулярности и planned.remaining без двойного счёта,200 парных недельных
bootstrap путей, p10/p50/p90, дневной и горизонтный риск,4 сценария и explanations
по wiring-v1.1. При плохой/короткой истории вероятность None. Модельные оценки,
не гарантия; исходный DTO не мутируется. Источник истинного риска — наблюдаемый счёт.
Tests: из backend python -m pytest tests/analytics tests/test_baseline.py -q →44 passed.
Ruff forecasting +analytics passed. Reviewer независимо повторил44tests и итоговую логику.
Fingerprint5файлов:3919c0d8269404c9cfc2a1113395d0e9a267026c0cc4ee7f6d3fc225f060b8dd.
Подробности/ограничения specs/forecasting.md; default84 пока до выбора окна на validation B4.

Для реальной интеграции требуется snapshot-events-v1 (прошу ACK A):
- передавать известные на as_of cancelled/paid/remaining0 события будущих occurrence,
  чтобы закрытый/отменённый платёж не возрождался из исторической регулярности;
- передавать активные просроченные события, а не только due_date>as_of:
  модель явно предполагает оплату завтра; это не доказательство срока;
- сохранять original snapshot для базы/сценария. Дедупликация понимает planned name
  против txn.INN+name; связь recurrence_group предпочтительна.
Текущий snapshot.py фильтрует cancelled и due<=as_of, поэтому READY pure сервиса
не означает, что эти случаи уже работают через приложение. DTO менять не требуется.

B0 уже INTEGRATED c5f423d, подтянут обычным merge dd9015b в чистую B ветку.
CI B1 70fb9b1 success40020486711; B2 b20b565 success40020765597.
B4 validation запущен:4среза апрель–июль2026,30д,150компаний, окна28/56/84 +baseline.
ETA несколько минут; holdout сентябрь только после фиксации выбора по validation.
Не выдаю отсутствие конечных метрик за завершённую B4.
