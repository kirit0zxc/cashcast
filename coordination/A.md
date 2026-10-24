# Статус A

state: WORKING
task: A29 role UI VERIFIED; A30 investigate lost manual-confirmation state; F2 blocked
code_sha: 47d2eeaf9232cf712715b958359ffab0d8e418d4
tested_sha: 47d2eeaf9232cf712715b958359ffab0d8e418d4
last_update: 2026-10-24T04:09:00Z
contract_version: archive-v1 + app-api-v1 + wiring-v1.1

## Следующее действие
Довести A4 и NIGHT-A-FULL, прочитать новые удалённые сообщения B и принять
проверенные пакеты. A008 ниже — актуальный handoff; старые записи — история.

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

## A-002 · ACK B-001 / wiring-v1

UTC: 2026-10-23T20:29:34Z
reply_to: B-001 (origin/agents/b-analytics e27a75c)
type: ack
task: A1/A2
contract_version: archive-v1 + wiring-v1
ETA: минимальный UI и предложения HTTP в течение 20 минут; heartbeat до 20:49Z.

Подтверждаю archive-v1 и четыре get_* factory. DTO пока не меняем.
Подтверждаю все четыре условия B-001: matcher получает только доступные на as_of
события и операции; remaining уже учитывает подтверждённые matches; proposals не
пишутся аналитикой в БД; ForecastInput только один account/RUB, неизвестная валюта
отклоняется; details JSON без сырых назначений. A подключает это на стороне snapshot/API.
A-001 опубликован c709472: прошу отдельный ACK app-api-v1 (accounts/import-presets).
Фронт готовится по текущим ручкам; временный UUID-input заменится выбором счёта после ACK.

Дополнение для согласования wiring-v1.1:
- Для HTTP explanations прошу details.explanations=[{kind,label,amount_minor?,source_ref?,detail:{}}]
  и details.summary (строка), без содержимого выписок. A валидирует перед выдачей.
- План-факт: GET /companies/{company_id}/plan-fact?account_id=&as_of= (response ниже
  предложу в specs после B2), подтверждённые matches учитываем один раз; неоднозначные
  предложения отображаем отдельно и не уменьшаем remaining автоматически.
- Снимок входа сохраняю при постановке job как JSONB: worker и сценарий читают
  зафиксированные входы, а не изменённую за время ожидания БД. Аддитивная миграция
  и сериализация остаются у A, чистые DTO B не меняются.
Ответьте ACK/изменения по explanations и snapshot; это предложение, не ваш ACK.

## A-003 · B0 INTEGRATED / heartbeat

UTC: 2026-10-23T20:37:23Z
reply_to: B-003, B-004, B-005
type: integrated
task: A1/A2
contract_version: app-api-v1 + archive-v1 + wiring-v1.1
code_sha: c5f423d398848f834f3fc997798c2c101fd7148d
tested_sha: c5f423d398848f834f3fc997798c2c101fd7148d
ETA: A1 пакет и B1 интеграция около 20:55Z; следующий heartbeat до 20:56Z.

B0 exact92d12fd принят обычным merge c5f423d и fast-forward integration/night.
34 backend tests и Ruff passed; независимый reviewer без блокеров; все3jobs CI
success https://github.com/kirit0zxc/cashcast/actions/runs/40020104106 . PR3.
Пробный обмен A001/B001/B003 и приём точного SHA с CI выполнены. Дальше можно работать
по длинной очереди. B: обнови чистую ветку из integration/night между пакетами.

ACK B004: wiring-v1.1 теперь согласован; документ и immutable snapshot у A.
Accounts/preset app-api-v1 уже реализованы локально; 37 tests passed. UI lint/build
passed; на браузерной проверке исправил обновление cache после login, проверка продолжается.
B1 READY4f922bc увидел; приму отдельным merge после A1 checkpoint, не заменяй свои файлы.
Для B2 жду точный формат proposals/дедупликации и предложу response plan-fact отдельно.

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

Примечание к времени: B005 уже наблюдается в remote70fb9b1 в20:37Z, хотя его запись
помечена20:38Z. Ориентируемся на Git SHA и ACK, не на точное совпадение часов двух ПК.

## A-004 · ACK allocation-residual-v1 / plan-fact-api-v1 proposal

UTC: 2026-10-23T20:44:40Z
reply_to: B-006, B-007
type: ack + proposal
contract_version: allocation-residual-v1 ACK; plan-fact-api-v1 proposal

ACK allocation-residual-v1: A обеспечит остаток каждой txn после confirmed allocations,
блокировку строк счёта при reconcile, предел суммы распределения и идемпотентность пары.
Candidate — альтернативы, не уменьшают remaining и не суммируются. DTO не меняем.
События/txn фильтруем по account/currency/as_of до matcher. B2 чистый сервис принимаю.

Предлагаю plan-fact-api-v1 (нужен ACK):
- GET /companies/{company_id}/plan-fact?account_id=UUID&as_of=YYYY-MM-DD
  → {account_id,as_of,items:[{event:PlannedEventOut,confirmed_amount_minor}],
     confirmed_matches:[{planned_event_id,transaction_id,matched_amount_minor}],
     proposals:[{planned_event_id,transaction_id,matched_amount_minor,confidence,reason,auto_confirm}]}.
  GET ничего не пишет; proposals из чистого matcher на остатках.
- POST по тому же пути с query account_id/as_of и CSRF: сохраняет только безопасные
  auto_confirm; возвращает тот же формат после повторной сборки. Повтор без новых
  фактов ничего не списывает. Неоднозначные кандидаты пока только показываем.
  Чужая компания/счёт 404. as_of не позже сегодняшнего UTC-дня.
Окончательная ручная аллокация кандидатов вне ночного MVP; не выдаём их за оплаченные.
Перед snapshot прогноза A выполнит тот же reconcile в своей транзакции, чтобы уже
оплаченный факт не остался ожидаемым потоком. Подтверждённые аллокации прошлого не
используем на более раннем as_of: смотрим дату txn и available_at события.

A1 code0b10b77: 38backendtests, Ruff, frontend lint/types/build, realChromium E2E passed.
PR4 candidate-a1 CI запущен. B1/B2 объединяются отдельным пакетом; snapshot далее.

## A-005 · ACK snapshot-events-v1 / model-version request

UTC: 2026-10-23T20:50:00Z
reply_to: B-008
type: ack + proposal
contract_version: snapshot-events-v1 ACK; model-version-v1 proposal

ACK snapshot-events-v1: snapshot передаст известные cancelled/paid/remaining0 будущие
события и активные просроченные, не отбрасывая их по due_date/status. Фиксация входа
enqueue уже локально реализована и проверена тестом изменения БД между enqueue/worker.
64backendtests+Ruff и Alembic check pass. Модельные эффекты сценария проверю после B3.

Для pinned model нужен публичный атрибут service.model_version (строка), совпадающий
с ForecastResult.model_version и включающий выбранное окно (например -w84). Прошу B
добавить его SeasonalForecastService в ближайшем пакете; get_forecast_service без args
сохраняется. Для старой baseline A оставит временный fallback на её константу.
Worker отвергает несовпадение версии; старый сценарий не пересчитывается новой моделью
молча. Это model-version-v1, просьба ACK.

Ожидаю ACK plan-fact-api-v1 из A004. Исторические confirmed allocations дополнительно
фильтруем по created_at самой связи; позднее подтверждение не становится знанием прошлого.
Правило можно зафиксировать отдельно от B4, который оценивается на банковских фактах.

## A-006 · B1/B2 INTEGRATED / A2 heartbeat / comparison-v1 proposal

UTC: 2026-10-23T20:56:37Z
reply_to: B-009, B-010, B-011
type: integrated + proposal
ETA: A2 кандидат около 21:15Z; следующий heartbeat до 21:16Z.

B1/B2 приняты в integration/night21eca62:63fulltests+Ruff, независимое ревью, зелёные
все3jobs включая realChromiumE2E https://github.com/kirit0zxc/cashcast/actions/runs/40021757914 .
Это также сквозная проверка A1 UI/счетов/импорта. B3/model-version exact1028b345
объединяется сейчас с A2;84fulltests локально проходят на текущем совместном WIP,
пока не объявляю tested SHA для незакоммиченного A2. B: обновляй чистую ветку между пакетами.

Уточнение исторического plan-fact (прошу ACK): POST пишет только на сегодняшнем
UTC-срезе, для старого as_of409 historical_reconcile_read_only. GET старого среза409
historical_plan_unavailable, если известный план редактировался после него: старой
версии полей нет в БД. В историческом прогнозе reconcile только читает; не записываем
нынешнюю аллокацию как знание прошлого. Это честное ограничение, а не восстановленная
история. Поля response не меняются, current-day POST/GET полностью работают.

Предлагаю comparison-v1 (нужен ACK): GET /forecasts/{scenario_id}/comparison.
Только для успешного сценария с base_forecast_id и успешной базы; доступ к компании.
Проверяем одинаковые account/as_of/horizon/data_version/model_version/seed, иначе409.
Ответ: {base_forecast_id,scenario_forecast_id,as_of,horizon_days,model_version,
points:[{point_date,base_balance_p50_minor,scenario_balance_p50_minor,delta_balance_minor}],
risk:{base:RiskOut,scenario:RiskOut}}. delta = scenario-base (отрицательный при допрасходе).
Причины уже подключаются из details.explanations/summary;501 убран на локальном A2.
Также исправлена оплата paid→remaining0 и запрет суммы ниже уже оплаченной части.

## A-007 · B0–B4 VERIFIED / новая цель владельца B5–B10

UTC: 2026-10-23T21:17:16Z
reply_to: B-012, B-013
type: integrated + owner_instruction
ETA: A3 comparison/UI уже локально проверены; A4 README/fresh demo далее.

Вся B0–B4 принята обычными merge, integration/night5bf8cd0.93fullbackendtests+Ruff,
Docker/realthroughAPIChromiumE2E, CIвсех3jobs success40024975206. PR7.
Сам повторил validation→config и holdout на исходномZIP: JSON exact match с отчётами B.
Исторические ограничения иcomparison-v1 ACKB012 получил. A2 доступен в integration:
frozeninputs/versionpinning, allocationsresidual+locks, explanations, paid/cancelled/overdue.
После A3 сообщу общий окончательный SHA. README идемосценарий завершаю.

ВЛАДЕЛЕЦ ПРЯМО РАСШИРИЛ ЦЕЛЬ B: требуется законченная аналитическая часть, а не
остановка на B0–B4. Работать до08:00МСК24.10.2026 (=05:00UTC24.10).
Новая точная очередь B5–B10 в coordination/NIGHT-B-FULL.md, START-B и PLAN обновлены.
Начни с ACK и плана пакетов. Пройденные B0–B4 не повторяй. Приоритет — качество
прогноза/риска, затем все указанные модули, дополнительные источники, сценарии,
устойчивость и интеграция. Нельзя подбирать модель по уже просмотренному сентябрю.
Новые интерфейсы/зависимости согласовываем как прежде; main/права/расходы не расширены.
Файл сам не возобновляет законченный goal: Диме нужно отправить текст продолжения.

## A-008 · A3 VERIFIED / расширенная цель A до09:00

UTC:2026-10-23T21:38:00Z
reply_to:B-012,B-013
type:integrated + owner_instruction
code_sha:5d80b71166b30e93344e7bb353d109a43ebed972
tested_sha:5d80b71166b30e93344e7bb353d109a43ebed972
ETA: A4 checkpoint около22:00Z, затем расширенная очередь до06:00Z.

A3comparison-v1+UI интегрирован; все3jobs CI40026907533 success, Chromium с реальным
API/worker.93backendtests. B0–B4 в общей версии. Новый NIGHT-B-FULL.md уже в integration.
B: прошу ACK расширенной очередиB5–B10 до08:00 МСК и приступай; без ACK не считаю
прочтение подтверждённым.

ВЛАДЕЛЕЦ УТОЧНИЛ: A продолжает до09:00 МСК24.10(06:00UTC), доводит серверную часть
и интеграции; frontend утром. Если B заканчивает раньше08:00, A назначает следующие
полезные пакеты. Правила в NIGHT-A-FULL.md, main остаётся человеку. Heartbeat чата A
на20минут до06:00UTC настроен; это не разрешает второй параллельный писатель.

FreshCompose18083+реальнаяC001:1131операция, все4сценария/сравнение, план/planfact,
причины, база не меняется,logout401. Restart сохранил1131txn/14runs/420points;
dump/restore в отдельную БД сверены. README/smoke A4 проходят ревью.
Это не завершение B5–B10 или калибровки; матрица недоделок — A4-VALIDATION.md.

## A-009 · ACK B-014 / model-registry-v2

UTC:2026-10-23T21:39:56Z
reply_to:B-014 (origin/agents/b-analytics49ddb50)
type:ack
contract_version:model-registry-v2

ACK ровно предложенной фабрики: optional точная model_version, explicit static
supported tuple, неизвестная версияValueError unsupported_model_version, без тихого
fallback. Default переключать только отдельным READY после измерений. Решение в
coordination/decisions/model-registry-v2.md. После твоего READY подключаю pinned вызов
в worker и тесты старого queued/scenario. Общие DTO не меняются.

Расширенную очередьB5–B10/B014 увидел, ACK получен, takeover не нужен. A4 завершаю,
далее собственный пакет надёжности очереди: найдено, что смерть worker на последней
попытке оставляет running навсегда; воспроизведу и исправлю с регрессиями.
CSV формат предложи как планировал: A готов сделать HTTP/ORM/preview/commit после ACK.
Следующий heartbeat до21:59UTC; продолжаю до06:00UTC по прямому запросу владельца.

## A-010 · ВЛАДЕЛЕЦ: GitHub Actions quota / уведомление B

UTC:2026-10-23T21:42:12Z
reply_to:none
type:owner_instruction
contract_version:night-ci-quota-v1

Владелец предупредил, что скоро закончатся Actions, и разрешил либо публичность,
либо продолжение при отказе CI. A выбрал ОСТАВИТЬ ПРИВАТНЫМ. На эту ночь обязательность
Actions заменена локальными проверками общего кандидата и одним reviewer по точному
SHA. Не делай workflow_dispatch каждого push/status/docs и не жди квоту бесконечно.
Настоящие падения тестов/сборки исправляем; отсутствие CI не называем success.
Причину quota записываем только при подтверждении, иначе not_run/cancelled/etc.
Решение: decisions/night-ci-quota-v1.md; AGENTS, оба START и NIGHT обновлены.
B: прошу ACK night-ci-quota-v1; продолжай очередь без блокировки Actions.
Main/права/видимость/расходы не расширены. Доставка пока не подтверждена твоим ACK.

## A-011 · ACK CSV adapter / HTTP proposal / A5 heartbeat

UTC:2026-10-23T21:47:10Z
reply_to:B-015 (origin/agents/b-analytics d39591a)
type:ack + proposal
contract_version:csv-obligations-v1; HTTP часть proposal

ACK чистого parse_obligations_csv и DTO ровноB015. Подробности в decisions/csv-obligations-v1.md.
A передаст source_name уже с accountUUID namespace, чтобы IDs разных счетов не
сталкивались; DBUUID/ORM/хранение provenance/tax_regime и атомарность остаются у A.
Исторические ограничения остаются. Будущий available_at не пропускаем молча.
Прошу ACK HTTP-части в документе: obligation-imports preview/atomic commit, source ID
conflict409 без перезаписи, те же auth/CSRF/изоляция. Чистый adapter можешь делать уже.

B5a exact2727fdd увидел READY, приму следующим пакетом после A5. A4 CIвсех3jobs
success40028577412, вintegration уже f00d3b5 с отдельным локально проверенным квотным
исключением A010 (новый Actions не запускался). A5 queue4регрессии + full97tests/Ruff,
реальный Compose/C001/4сценария PASS; reviewer перед push. Следующая связь до22:07UTC.

## A-012 · B5a/registry общий кандидат / API commit race

UTC:2026-10-23T21:57:25Z
reply_to:B-015,B-016
type:working
contract_version:model-registry-v2; csv-obligations-v1 ACKадаптера/HTTPproposal

A5 очередь уже в integration420a8fd,97tests/reviewer/Composeпройдены, Actionsnot_run
по явному исключению владельца A010. Твой точный f9201dbe и B5a2727fdd объединены
локально обычным merge; worker передаёт закреплённую версию, неизвестная даёт
unsupported_model_version без fallback. Default1.0-w84 не менялся. Общий150tests/Ruff,
C001smoke4сценария и реальныйChromiumE2E на18083passed. Кандидат на ревью до публикации.

Найден и исправлен системный APIдефект: yieldcommit выполнялся после отправленного
202, немедленныйGETjob давал404. Functionscope фиксирует commit до ответа; ASGIтест
показывалresponse→commit дофикса, теперьcommit→response, commitfailure→500. Минимальная
границаFastAPI0.121 вpyproject/lock; закреплённые версиипакетовне менялись.

B: при ближайшем fetch прочитай A010/night-ci-quota-v1 и ACK (неблокирующие Actions,
private, локальныетестыобязательны). A011 ACK CSVадаптера уже опубликован в420a8fd,
прошу отдельно ACK HTTPproposal. Если большой benchmark занят, можно первым небольшим
пакетом отдать CSVparser, чтобы A параллельно подключил настоящий preview/commit.
Следующая связь до22:17UTC; после интеграции начну хранение/importслой обязательств.

## A-013 · B5a/registry VERIFIED / ACK B-017 / A6

UTC:2026-10-23T22:09:44Z
reply_to:B-017,B-018
type:integrated + ack
code_sha:e17b64aee1af83904a2d57c65935fa26861713be
tested_sha:e17b64aee1af83904a2d57c65935fa26861713be

B5a2727fdd и registryf9201db приняты обычным merge e17b64a,150fulltests+Ruff,
Docker/C0014сценария/ChromiumE2Epassed, reviewerready. Actionsnot_run поA010. PR13.
B017 ACK quota+CSVHTTP получен, спасибо; решение о приватности доставлено и принято.
CSVHTTP теперь согласован; начинаю хранилище/миграцию/preview/atomic commit.
B018 exact88c56b6 увидел READY, приму после текущего A6пакета.

A6локально156tests+Ruff, реальныеC0014сценария/E2Epassed: невалидные UUID/денежные
и seedпереполнения теперь422. APIформат нормальных запросов сохраняется, OpenAPI
уточняетformatUUID/границы. Shared DTO не менялся. Реальный502послеAPIrecreate тоже
исправлен: nginxдинамическиобновляетDockerDNS; сменаIPбезwebrestartпроверена.
Ни квотные отказы, ни локальныепровалы не объявлялисьsuccess.

CSVparser как следующий маленький пакет B018 очень поможет параллельной интеграции,
новую задачу поверх твоей очереди пока не добавляю. Следующий heartbeat до22:29UTC.

## A-014 · A6 VERIFIED / B5b selection reproduced

UTC:2026-10-23T22:14:47Z
reply_to:B-018
type:working + information

A6d37d659 уже в integration/night:156tests/reviewer/реальныйстендpassed, PR14.
B5b exact88c56b6 объединён локально обычным merge:189fulltests+Ruffpassed.
Сам независимо повторил select_v2.py на исходномZIP,55.05сек. Все числа ошибок,
кохорты/исключения/sourcehashes и решение совпали с selection-v2.json; runtime_ratio,
profiles/elapsed не сравнивал на равенство. В собственном run все альтернативы<3x,
но MAEкритерий не прошли; оставлен legacy_w84. Результат внеGit в preparation.
Общий пакет проходит одного reviewer, default/modelregistry не меняю.

ACK CSVHTTP B017 подтверждён, готовлю ORM/миграцию/preview/atomic commit. Спасибо за
следующий небольшой parserпакет: финальное подключение/совместные тесты после него.
Подтверждение model-quality новой вероятности не заявляется; B6 ещё в работе.
Следующая связь до22:34UTC. A продолжает до09:00МСК, даже после исходного A0–A4.

## A-015 · B5b INTEGRATED / ACK B-019 parser bounds

UTC:2026-10-23T22:22:10Z
reply_to:B-018,B-019
type:integrated + ack + working
code_sha:8d011c7e55690fca8d2a6165e82f4543a1085e6a
contract_version:csv-obligations-v1 parser-v1

B5b принят в integration/night8d011c7 через PR15:189backendtests, Ruff, независимое
полное воспроизведение selection и reviewer итогового дерева. Default не переключён.
Actionsnot_run по квоте. B8a822b6cd проверяется отдельным общим кандидатом; границы B019
подтверждаю полностью, точная запись в decisions/csv-obligations-v1.md.

A7 работает над storage/миграцией/HTTP по B017, namespaceaccountUUID:source_name.
Прежние события/оплаты сохраняются, изменённый оригиналsourceID конфликтует целиком.
Прошу дополнительно ACK аддитивных read-only полей PlannedEventOut:
counterparty_ref:str|None,provenance:str|None,tax_regime:str|None. Храним их с CSV,
ручной create/patch не меняем. Для старых строк null, никаких выводов налогового режима.
Доступ прежний только членам компании. До ACK в публичный DTO не добавляю.
Следующая связь до22:42UTC; B6None fallback принимаем честно без обещания калибровки.

Дополнение22:24UTC:207тестов и Ruff общего B8a passed, но reviewer нашёл P2:
sources.py проверяет control characters после strip(), поэтому tab/newline по краям
id/cells теряется и недопустимый sourceID принимается. Просьба B: проверять исходные
cells и header до strip(), также source_name до нормализации; добавить регрессии
leading/trailingtab и quotednewline. В header strip тоже скрывает controlcharacters.
Полный запрет уже ACKB019/A015; это исправление согласованной схемы, не новыйконтракт.
Merge-кандидат пока отменён, parser не интегрирован. A продолжает независимый storage.

## A-016 · A7 local integration / CSV capacity proposal

UTC:2026-10-23T22:34:00Z
reply_to:B-019,A-015
type:working + proposal
contract_version:csv-obligations-v1-capacity (ACK requested)

A7 реализован локально: ORM/additive migration, preview/atomiccommit, canonical original
sourcepayload, provenance/tax/ref persistence, snapshot/matcher useactualcounterpartyref.
14новых HTTP/PostgreSQLтестов passed inclconcurrentpreview/commit, companyisolation,
rollbackwholebatch, manualpaidpreserved, historicalguard. Full221passed+Ruff+Alembiccheck.
FreshCompose18083 realworker: новыйCSVсчёт321руб меняетp50 ровно-32100коп сdue_date;
repeatcommit/immutablebase прошли. Новыеread-onlyDTOполя пока ждут ACKA015.
Независимые3HTTPregressions leading/trailingtab/quotednewline воспроизвели P2parser,
исправление остаётся уB. A7checkpoint сохранён внеGit, неREADY/неintegrated.

Второй reviewerP2: parserдо10000rows, но forecastguard2kplanned_events и totalremaining
<=9e15minor; успешныйCSVcommit2001документа сделает текущийaccountнепрогнозируемым.
Предлагаю add-on: под accountlock до записи проверять совокупность existing+newplans
(включаяpaid/cancelled дляcount), count<=ResourceLimits().events и totalremaining
<=MAX_MONEY_MINOR, identicalskipsнеувеличиваютбюджет. Превью по-прежнему10000rows,
несовместимыйcommit целиком409forecast_capacity_exceeded без новыхevents/paidreset.
Те же проверки применю к manualcreate/patch, чтобы не обойти ограничение. Никакого
молчаливого удалениястарыхсобытий/повышенияguard. Прошу ACK либо точныйконтрвариант.
Дополнительно планирую раннийvalidate_input передenqueue с422кодомtypedguard,
чтобы неподдерживаемыйsnapshot не создавал заведомо failedjob. Старыеworkerguardsостаются.

ПослеA7 следующаяA-задача: строгийразбор выписок (сейчас1e9превращаетсяв19,
unknowndirectionвOUT, неизвестнаяencodingможетдать500), затем сохранённаяистория.
B6 продолжай; этонеперехватаналитики. Следующийheartbeatдо22:54UTC.

## A-017 · A7 VERIFIED / B6 integrated / default-switch ACK

UTC:2026-10-23T22:48:23Z
reply_to:B-020
type:integrated + verified + ack + proposal
code_sha:3c4edf76e889e46f3056c5661060d6ff6c6127cf
tested_sha:3c4edf76e889e46f3056c5661060d6ff6c6127cf
contract_version:csv-obligations-v1-capacity ACK; model-registry-v2

PR16/integration3c4edf7 содержит точныйBREADY6c12 +A7 HTTP/storage/capacity/поляпроисхождения.
ОбаP2 и C1вHTTPsource_name исправлены. Полный266backendpassed; после2новыхрегрессий
профильныйA7набор23passed. Ruff/Alembiccheck/frontlint/typecheck/ChromeE2E1passed.
FreshCompose18083 точного3c4edf7: CSV→realworker→p50-32100коп, repeat/baseimmutable,
C1HTTP422; C0011131rows+все4сценария тожеpassed. Reviewer finaltree
eca256f2bfd3e541b835cef7f7738790df48bec0 замечанийнеоставил. Actionsnot_run поquota.

Полностью независимо повторилcalibrate_v2: всеmetrics/cohorts/config/sourcehashes/
decision совпали точно; исключены elapsed_seconds и productprofiles/timing. Runtime71.67s.
product_probability_verifiedFalse подтверждён, не выдаёмNone за0. Default пока1.0.
ACK отдельного переключения2.0послеBпроверок: A-ownedfrozenmodeltestисправлен,
берёт queuedmodel изGETпослеenqueue иутверждаетего послеизмененияfactory. Ужеpassed.
Пришли отдельныйREADYdefault-switch; послеинтеграцииповторюCompose2.0/4сценария/API/UI.

A8: строгийstatementparser внепродуктовогокода пока27puretests passed; подтвердил
старыеошибки1e9→19руб/unknowndirection→out/codecLookupError/округление3знаков.
ДоведуHTTP/DBрегрессии и отдельныйкандидат, B-ownedфайлыаналитикинетрогаю.

Следующие полезныеAAPI прошу ACK по точнымdraftрешениям (ещёне реализованы):
forecast-history-v1.md — сохранённыерасчёты послеreload/login сjob/status иcursor;
plan-fact-confirm-v1.md — явное ручное подтверждение текущегоproposal подaccountlock,
остатки/идемпотентность/CSRF. Purematcher остаётся уB. Следующаясвязьдо23:08UTC.

## A-018 · A8 VERIFIED / integration7c82d69

UTC:2026-10-23T22:57:08Z
reply_to:A-017,B-020
type:integrated + verified + heartbeat
code_sha:7c82d6982b5d301465f7442c575d1fb811e9be0b
tested_sha:7c82d6982b5d301465f7442c575d1fb811e9be0b

A8 вPR17/integration7c82d69: strictstatementmoney/knownDirections/codec/CSVshape,
longbankID200сboundedhashfingerprint, oldshortkeys unchanged, previewaccountlock.
301fullbackendtests+Ruffpassed, reviewer tree df9dd29cc6ff3724843d9da58cc198b6c2f26153
беззамечаний. pg_blocking_pids подтвердилблокировку. Docker18083 live4badCSVpreview
failed/commit409/ledgerunchanged; C0011131rows+4scenarios+ChromeE2E1passed.
Actionsnot_run поquota, repo private. Строгийparser не изменяет B-ownedаналитику.

A017/B020 поdefault2.0 актуальны: тестзакреплённойверсииисправлен; жду отдельный
проверенныйswitchпакет. НовыйA9 пока ждёт ACK двухdraftконтрактовA017 (history,
manualproposalconfirm); есть независимыеREADME/requirements/отрицательныетесты.
Следующийheartbeatдо23:17UTC. B7/B8/B9/B10 не объявленыготовымибезREADY.

## A-019 · A9 VERIFIED / CHECK-IN A019-20261023T2325Z

UTC:2026-10-23T23:25:00Z
reply_to:B-020,A-017
type:integrated + verified + CHECK-IN
code_sha:84be7a9430fce1cfe7da83e55d85cf1295cefd6b
tested_sha:84be7a9430fce1cfe7da83e55d85cf1295cefd6b

A9/PR18 в integration/night: минимальные формы ручного платежа и CSV обязательств,
preview/commit, остатки/происхождение, отмена, повторный импорт. Новых API/DTO нет.
Frontend lint/typecheck/build passed; настоящий Docker18083, Chromium 2 E2E passed:
старый импорт/сценарий + новый план/ошибочныйCSV/commit/forecast/cancel/reload/reimport.
Отменённый план не возродился, дубля нет. Reviewer final tree
05f6ff02209b2accc7722c31394588302faa6295 без замечаний. Backend A8:301 passed Windows;
сейчас полный Linux-прогон в одноразовом контейнере, только отдельная cashcast_test.
Actions not_run по night-ci-quota-v1; main/видимость не менялись.

Формальный CHECK-IN по PROTOCOL §7: успешные fetch/ls-remote всех веток наблюдают
B a7715dd95f2a65d0316d27c1587c66cbc5408fdf, integration/A84be7a9; fallback-веток нет.
Последняя объявленная B ETA22:56UTC прошла, но это не доказательство остановки.
Прошу текущую задачу/ETA и ACK A017: тест queuedversion исправлен, default2.0 ACK;
жду отдельный READY switch. Точные history-v1/manualconfirm-v1 draft также ждут ACK.
Отсчёт только от публикации этого CHECK-IN; повтор через30/60 минут, новые сообщение,
commit или ETA сбрасывают его. Сейчас чужую область не беру, продолжаю A-проверки.
Следующий heartbeat не позднее23:45UTC.

## A-020 · Linux301passed / A10 VERIFIED / mapping repair proposal

UTC:2026-10-23T23:31:00Z
reply_to:A-019,B-020
type:integrated + verified + proposal
code_sha:08068e069d66a684f4cd98deb0b697bb11300beb
tested_sha:08068e069d66a684f4cd98deb0b697bb11300beb

Полный Linux backend A9:301passed28.26s, ephemeralcontainer/sourceRO/отдельная
cashcast_test. Дополнительный A10/PR20 вintegration08068e0:2HTTP/PostgreSQLtests
подтверждают зарегистрированную2.0 через очередь/worker/JSONB, null probability,
закреплённую модель после смены default, все4сценария/comparison/immutablebase.
2pytest+Ruffpassed, reviewer tree321f8e4771476b70c1e2fdf8bc48120063e69f87 ready.
Аналитика/default/публичныеDTO не менялись, качество модели этими тестами не доказано.
Итоговый утренний draft PR19 integration/night→main открыт без Approve/merge.
Actionsnot_run поquota; новые2tests не назывались полным303-прогоном.

Новый подтверждённый A-баг: ошибочныйCSVdelimiter, затем исправленный для техже
байтов → preview0errors/statusfailed/старыйid, commit409. Точныйproposal
decisions/statement-mapping-v1.md: previewidentity account/rawSHA/canonicalmappingSHA,
новыйpreviewдля исправления доcommit; послеcommitдругойmapping409; accountlock,
additivebackfill/noledgerchanges. Прошу ACK перед реализацией. Пока только proposal.

Следующий независимый A11: подключить остальные3 уже согласованныхсценария в
минимальном UI с целями из savedexplanations; без новыхAPI/DTO/дизайна.
A019 CHECK-IN остаётся: публикация≈23:25:40UTC; отсчёт консервативно с23:26UTC,
повтор не раньше23:56/00:26. Новая B-активность сбросит таймер; takeover сейчас нет.
Следующий heartbeat до23:51UTC.

## A-021 · A11 VERIFIED / remaining ACKs / A12 precise display

UTC:2026-10-23T23:42:20Z
reply_to:A-020,A-019,B-020
type:integrated + verified + working
code_sha:2cb8a25411951219848bb757a0e7dea904beeff2
tested_sha:2cb8a25411951219848bb757a0e7dea904beeff2

PR21/integration2cb8a25: все4сценария в минимальномUI, цели из savedexplanations,
не сегодняшний изменяемыйсписок; отсутствиецели объясняется. Lint/types/buildpassed,
новый чистый Compose18084:3ChromeE2Epassed19s; повтор all4 на тойжеБДpassed10.2s.
Reviewer tree d7dbc45b23e1c84b2a8d8837e1878cc2959fad79 ready. Причины первыхдвух
падений отражены attemptsA007, assertions/таймаут не ослаблены. Backendне менялся.
Дополнительные2tests2.0 также прошлиLinux3.63s. Это301full+2profile, невыдуманный303full.

Следующий A12: воспроизведена потерякопейки в отображении допустимойграницы:
8999999999999999minor через Number/100 и Intl показываются как89999999999999.98RUB,
вместо.99. Исправлю чистыйUIformatter через целыеBigIntчасти, unitregressions без
новыхdependencies/API, финансоваяарифметикаbackend не меняется. Затемfrontendhandoff.

A017 history/manualconfirm и A020 mapping ждут точногоACK. Default2.0 switchREADY
тоже жду; A-ownedqueuedversiontest исправлен давно и ACKA017 остаётся в силе.
Последний fetch B a7715dd, fallbacknone. CHECK-IN A019 с23:26UTC не сброшен,
первый повтор после23:56UTC, до порога чужиеобласти не беру. Actionsnot_run/private.
Следующийheartbeatдо00:03UTC, либо раньше приREADY/новомпакете.

## A-022 · A12 VERIFIED / frontend dev dependency audit

UTC:2026-10-23T23:48:00Z
reply_to:A-021,A-019
type:integrated + verified + working
code_sha:777ff2212eb04edc359fd84eb5e67979841b5012
tested_sha:777ff2212eb04edc359fd84eb5e67979841b5012

PR22/integration777ff22: точныйBigIntmoneyformatter,4unitpassedWindows24.19/Linux24.18.1,
lint/types/buildpassed, реальный пересобранный Docker18084:3ChromeE2Epassed15.2s.
Reviewer treeb17a20d7c4f708c2b3a550c9dc0df915ee7fb449 ready, API/backendнеизменны.
Новый unitstep всуществующемCI, безновойбиблиотеки/dispatch; Actionsnot_run/private.

A13 WORKING: фактический npm audit при сборке дал4advisorygroups (2low/1moderate/1high),
в devtools eslint/plugin-kit/esbuild/vite. Изучаю совместимоеобновление Vite6.4.4 и
ESLint/@eslint-js9.39.5: registryподтвердил plugin-react4.3.4peerподдержкуVite6,
Node24допустим. Не forceauditfix/не latestвслепую. Послеустановки нужныновыйaudit,
lint/types/unit/build/Docker/E2E/reviewer; сейчасисправленным не объявлено.
Далееfrontendhandoffдокументация/минимальныйplanfactUI существующегоGET/POST.

A019 CHECK-IN по-прежнему с23:26UTC, первыйповтор после23:56UTC. ACK A017/A020
и BdefaultREADY отсутствуют. Чужие файлыаналитики/default не меняю до протокола.
Следующийheartbeatдо00:08UTC либо по результатупакета; CHECK-INповтор отдельный.

## A-023 · CHECK-IN repeat1 / A13+A14 VERIFIED

UTC:2026-10-23T23:56:04Z
reply_to:A-019,A-022,B-020
type:CHECK-IN + integrated + verified + working
code_sha:589fcfd93825b4b4c3f60863b89b575aaa8ac374
tested_sha:589fcfd93825b4b4c3f60863b89b575aaa8ac374

Первый формальный повтор A019-20261023T2325Z. Успешный fetch/ls-remote всех источников
в23:56UTC: B a7715dd95f2a65d0316d27c1587c66cbc5408fdf, A/integration589fcfd,
fallback-веток нет. B020 по-прежнему последняя запись, новыхACK/ETA/READY нет.
B, пожалуйста, пришли текущуюзадачу/ETA/ACKA017/A020/defaultswitchREADY.
Это не новый отсчёт: консервативное начало23:26UTC сохраняется. Следующий повтор
после00:26UTC; intent не ранее00:56UTC+15мин. При B-активности таймер сбрасывается.
Перехвата сейчас нет, работаю в собственной области.

A13 PR23/integrationd06e1f1: exactdevtoolupdates, audit0known, lint/types/4unit/build,
Linuxnpmci/build/start и3ChromeE2E14.9s passed; reviewer treeec13d99 ready.
A14 PR24/integration589fcfd: frontend-handoff готов, исправлена HttpOnlyнеточность,
reviewer tree4e15046a49ab80fa9e89517b4585b7d8d9b442ed ready. Это docs-only, продукт
не изменился отA13; testsнеповторялись. API/backend/defaultнеизменны, Actionsnot_run.

A15 WORKING: минимальная видимость план-факта через уже согласованные GET/POST:
план/подтверждённаясумма/остаток/альтернативы и только безопасный auto-reconcile.
Без новой ручки manualconfirm, без графика с выдуманными фактическими датами.
Продолжу profileE2E и reviewer. Следующийheartbeatдо00:16UTC.

## A-024 · A15 VERIFIED / next server resource preflight

UTC:2026-10-24T00:11:30Z
reply_to:A-023,B-020
type:integrated + verified + working
code_sha:15bb61f54b4afa57712562fe35f9546cc259ac53
tested_sha:15bb61f54b4afa57712562fe35f9546cc259ac53

PR25/integration15bb61f: текущийplanfactUI/read-onlyGET/явныйautoPOST, связанныеоплаты,
остатки/просрочка/альтернативы. ReviewerP2 staleafterforecastenqueue воспроизведён
краснымChrome на18084; исправлены обеqueryinvalidations безпотериaccepted/job.
Finaltree85192933cf462b7ca6b801adb0f4274759b92873 reviewerready. Lint/types/4unit,
LinuxDockerbuild/startpassed. Свежий18085:5ChromeE2Epassed23.1s, новое0→paid через
forecastбезreload проверено на ещёнеоплаченномдокументе. Backend/APIне менялись.
Старый созданныймной18084 остановлен ссохранениемvolume; текущий18085работает.
Итоговыйdraft PR19 обновлён; онпо-прежнемунеодобрен/неслит. Actionsnot_run/private.

A16 WORKING/audit: guard50k/4k/2k проверяется послеORM-load/snapshotserialization;
createforecast передним ещё вызываетplanfactmatcher. Проверю воспроизводимыйранний
SQLpreflight техже согласованныхResourceLimits до тяжёлойсборки/сопоставления,
безновыхpureDTO/модели/повышениялимитов. Это поиск A-ownedинтеграционногодефекта,
необещаниеproductionнагрузки; пока ни новогоguard, ни тестовневыдаюзаготовое.

ACK A017(history/manualconfirm)/A020(mapping), defaultREADY по-прежнему ждутB.
ПоследнийB a7715dd, fallbacknone. ИсходныйCHECK-IN с23:26UTC; следующийформальный
повтор после00:26UTC, intentнераньше00:56+15мин. Чужаяобластьсейчаснеизменяется.
Следующийheartbeatдо00:31UTC, CHECK-INповтор отдельно своевременно.

## A-025 · CHECK-IN repeat2 / A16 VERIFIED

UTC: 2026-10-24T00:28:00Z
reply_to: A-019,A-023,B-020
type: CHECK-IN + integrated + verified + working
code_sha: 98309881a25633d91d73750e5972a55fb84aa2b5
tested_sha: 98309881a25633d91d73750e5972a55fb84aa2b5

Второй формальный повтор исходного A019. Успешный fetch обеих рабочих веток,
integration/night и fallback refs в 00:26 UTC: B по-прежнему
a7715dd95f2a65d0316d27c1587c66cbc5408fdf, последнее сообщение B020, fallback refs нет.
Новых B-коммитов, ACK, ETA и READY не наблюдаю. Это не утверждение о состоянии
процесса на другом ПК. B, пришли текущий checkpoint/ETA и ответ на A017/A020.
Начало отсчёта остаётся 23:26 UTC, intent возможен не раньше 00:56 UTC,
затем ещё 15 минут и успешная повторная проверка всех источников активности.
Перехват сейчас НЕ активен; новая активность B сбрасывает отсчёт.

A16 принят в integration/night через PR26, без изменения main. SQL row preflight
до matcher/ORM, те же согласованные лимиты и causal-фильтры. Полный backend:
308 passed Windows 47.89s и Linux 47.85s; Ruff и Alembic check passed.
OpenAPI export без изменения контракта. Пересобранные API/worker на стенде 18085:
5 Chromium E2E passed 19.1s. Независимый reviewer: tree
92d3821471d912280f9e3ffceecc7ce49733270b, ready. Actions not_run по quota-решению;
отсутствующие проверки не названы зелёными, приватность сохранена.

Дальше независимый аудит A-owned API/интеграций и документации. History API,
manual confirm и mapping-v1 пока proposals без ACK B; default всё ещё 1.0.
Следующий heartbeat до 00:48 UTC; formal intent только после 00:56 при выполнении §7.

## A-026 · A17/A18 VERIFIED / A19 existing category API in UI

UTC: 2026-10-24T00:39:01Z
reply_to: A-025,B-020
type: integrated + verified + working
code_sha: 22f49dd9378c6731e42a7b668ccc18fc2755acdb
tested_sha: 22f49dd9378c6731e42a7b668ccc18fc2755acdb

A17/PR27/3d18ac6: настоящая гонка одинаковых scenario POST давала [500,202].
Теперь account lock, оба 202 с одним run/job. Профиль 8 Windows passed, полный
Linux 309 passed 43.52s, Ruff passed, пересобранные API/worker и четыре формы:
1 Chromium E2E passed 10.3s. Reviewer final tree 27bdf3b ready.

A18/PR28/22f49dd: одинаковый output seed мог дедуплицировать сценарий другой базы.
Новые ключи включают base ID; старый run переиспользуется только для своей базы,
не переписывается. Три новых проверки new/legacy lineage и old-repeat, плюс
concurrency: 4 Windows passed. Полный Linux 312 passed 45.25s, Ruff passed;
пересобранные API/worker 18085, четыре формы: 1 Chromium E2E passed 10.4s.
Reviewer final tree 1fa6189980a7082bd623a314549120b9fad716d9 ready. DTO, миграции,
модель/default и base input/results не изменены. Integration FF, main не тронут.

A19 WORKING: минимальный UI для уже существующего PATCH transaction category.
Без нового API/словаря/дизайна. Нужно проверить сохранение после reload и повторного
импорта, manual source и неизменность ранее рассчитанной базы. Правка влияет на
следующий новый расчёт; сохранённый forecast не должен молча пересчитываться.

Последний успешный fetch: B всё ещё a7715dd/B020, fallback refs нет, новых ACK/ETA
не наблюдается. Исходный CHECK-IN 23:26 остаётся; intent не раньше 00:56 и ещё15мин.
Перехват не активен. Actions not_run/private; следующий heartbeat до00:59UTC,
либо раньше при новом B READY/результате. Formal intent отдельный после порога.

## A-027 · A19 VERIFIED / bank operation conflict proposal

UTC: 2026-10-24T00:48:20Z
reply_to: A-026,B-020
type: integrated + verified + proposal
code_sha: 84d1b1cf9ebf7b89b006e250691478d442e0efc1
tested_sha: 84d1b1cf9ebf7b89b006e250691478d442e0efc1

A19 PR29 принят FF в integration/night: существующий PATCH category в кабинете,
источник manual/auto и сохранение после reload/reimport без изменения saved run.
Lint/types/4unit/build и Linux Docker build/start passed. Все6 Chromium E2E passed
26.4s; по замечанию reviewer тест повторного значения усилен (fees↔tax), два
реальных повтора passed7.8s. Reviewer final tree
97fbb80842e3f494e8dfbe9cb3bd98ad3d03fd64 ready. Backend от22f49dd не изменялся,
полный Linux312 остаётся последним full-suite. Draft main PR19 обновлён, не одобрен.

Новый подтверждённый дефект: второй файл с прежним bank ID/новой суммой skip-ает
операцию, но обновляет остаток. Probe: оба commit200, ledger10000/balance20000.
Нужен ACK точного decisions/statement-operation-conflict-v1.md: одинаковый source
payload skip, изменённый ID commit409 transaction_id_conflict с полным rollback;
разный payload ID внутри файла failed preview; без нового DTO/миграции/перезаписи.
Пока proposal, исправление не заявлено. Начальный запуск probe имел ошибку двойной
регистрации pytest plugin; повтор через обычные fixtures cashcast_test подтвердил
дефект. Временная копия probe удалена; сырья и секретов в Git нет.

B по-прежнему a7715dd/B020; новые ACK/ETA не наблюдаются. Прошу ответить на A017,
A020 и A027 и прислать собственный checkpoint. CHECK-IN с23:26 не сбрасывается;
intent не раньше00:56, потом15мин и повторный успешный fetch. Перехвата пока нет.
Actions not_run/private. Следующее формальное действие после00:56 при отсутствии
новой активности; до этого только собственная независимая область.

## A-028 · TAKEOVER-INTENT / A20 VERIFIED

UTC: 2026-10-24T00:56:13Z
reply_to: A-019,A-023,A-025,A-027,B-020
type: TAKEOVER-INTENT (NOT ACTIVE) + integrated + verified
code_sha: ee70c690eeebcc956c4153134b73dd9e6b520ee0
tested_sha: ee70c690eeebcc956c4153134b73dd9e6b520ee0

Успешный fetch обеих рабочих веток/integration/fallback и ls-remote fallback после
00:56 UTC: A и integration ee70c690eeebcc956c4153134b73dd9e6b520ee0;
B a7715dd95f2a65d0316d27c1587c66cbc5408fdf, последнее B020/ETA22:56UTC,
новых ACK/коммитов/ETA нет; fallback refs нет. CHECK-IN с23:26UTC опубликован,
повторы A023 после23:56 и A025 после00:26 сохранены. 90 минут подтверждённого
отсутствия наблюдаемой активности истекли. Состояние процесса на ПК B неизвестно.

Это последнее предупреждение, НЕ начало перехвата. Возможный старт аварийной работы
не раньше 2026-10-24T01:14:00Z, то есть с запасом более15мин после публикации.
Перед стартом нужны новый успешный fetch всех источников, отсутствие новой B-активности
и отдельная запись TAKEOVER-ACTIVE. Любой новый ACK/commit/ETA до старта отменяет
отсчёт. Ошибка сети запрещает старт. B, пришли checkpoint/ETA/ACK или RETURN с WIP.

Если условия сохранятся, временно A берёт только необходимые MVP-задачи:
1. Отказ при конфликтующем bank ID и восстановление preview после исправления mapping.
2. Чтение истории сохранённых прогнозов, чтобы результат открывался после reload.
3. Явное подтверждение неоднозначного plan-fact proposal с атомарным бюджетом.
4. Активация уже интегрированной guarded2.0 с probability=None, без ретюнинга модели.

Точные пути предполагаемого fallback-пакета (новые перечислены намеренно):
- backend/app/modules/imports/{parser.py,service.py,identity.py}; core/models/ledger.py;
  backend/migrations/versions/20261024_statement_mapping.py.
- backend/app/api/v1/forecast_history.py; api/schemas/forecast_history.py;
  api/v1/plan_fact.py; api/schemas/plan_fact.py; app/modules/integration/plan_fact.py;
  backend/app/main.py. Все сокращённые api/core пути относятся к backend/app/.
- backend/app/modules/forecasting/service.py — только default на готовую2.0;
  frozen legacy, расчётные параметры, B7/WIP и evaluation не переписываются.
- backend/tests/test_{forecast_history,plan_fact_confirm,statement_mapping,
  statement_conflicts,default_guarded}.py; существующий test_guarded_model_api.py.
- frontend/src/shared/api.ts; features/forecast/{ForecastHistory,ForecastPanel}.tsx;
  features/planning/PlanFactPanel.tsx; features/imports/StatementImport.tsx
  (features относительно frontend/src/); e2e/{forecast-history,plan-fact-confirm,
  import-mapping}.spec.ts относительно frontend/.
- specs/{api,data-model,openapi,frontend-handoff,architecture} с прежними расширениями;
  README.md; coordination/A.md, attempts/A.md, REQUIREMENTS.md и уникальное временное
  coordination/decisions/fallback-a-20261024T0114Z-v1.md.

Ветка будет отдельной agents/fallback-a-20261024t0114z от свежей integration/night;
собственный checkpoint сохранён, B-ветка/WIP не сбрасываются. Временное решение
контрактов не является ACK B. Если B вернётся — остановка пересекающихся правок,
checkpoint/HANDOFF и явное согласование. Интегратор остаётся только A; main/права/
приватность/платные сервисы неизменны. Локальные тесты/reviewer обязательны, quota
не отменяет реальные дефекты. До старта чужая область и неподтверждённые API не меняются.

A20 PR30 уже VERIFIED/integration ee70c69: GET план-факта shared account lock,
согласованный before/after без записей от GET. Профиль Windows/Ruff passed;
полный Linux313passed46.97s; реальные Docker API/worker18085 и2ChromePFpassed5.1s.
Reviewer final tree fd7625d90dcff024aaa28e937fc507cf11cbeea4 ready. Actions not_run.

## A-029 · A21 VERIFIED / guarded2 QA / intent publication time

UTC: 2026-10-24T01:04:23Z
reply_to: A-028,B-020
type: integrated + verified + heartbeat (intent NOT ACTIVE)
code_sha: 461f6f819036f3e9c9a7aa9fa31cf7d54ae83216
tested_sha: 461f6f819036f3e9c9a7aa9fa31cf7d54ae83216

A21 PR31 FF/integration461f6f8: OpenAPI теперь описывает существующие409/500,
413 у двух загрузок, убрано устаревшее обещание501. Это только response annotations:
структурное сравнение всех остальных частей schema идентично; 21paths,5fixtures
и Ruff passed. Reviewer tree5856f70be84edb016368527f09ed3c3a222411c9 ready.
Продуктовые313Linux/6Chrome не повторялись ради описаний; их checkpoint указан выше.

Дополнительная QA до активации: ephemeral Linux с source readonly, отдельной
cashcast_test и явным выбором уже зарегистрированной GUARDED_VERSION только в
памяти тестового процесса. Полный suite313passed43.69s. Исходный service.py и
default стенда не изменены, B-область не редактировалась. Это подтверждение
совместимости, не активация и не новая метрика качества вероятностей.

A028 фактически опубликован commit9df34c8004f81f3b5473f46eda5921948fb68052,
успешный push завершён не позднее00:58:18UTC. Поэтому earliest ACTIVE остаётся
max(01:14UTC, publication+15min)=01:14UTC. Последний успешный fetch: B a7715dd/B020,
fallback refs нет; новых ACK/коммитов/ETA не наблюдается. Сначала ждём ответ, затем
повторный успешный fetch всех источников и отдельная ACTIVE-запись, если §7 выполнен.
Новых совместных API/банковских правил/default до этого не реализую. Чистое дерево,
собственный checkpoint сохранён. Следующая проверка до старта; новая активность
отменяет отсчёт. Actions not_run, main/private без изменений.

## A-030 · TAKEOVER-ACTIVE (limited MVP)

UTC: 2026-10-24T01:14:16Z
reply_to: A-028,A-029,B-020
type: TAKEOVER-ACTIVE
role: A temporarily covers only the MVP scope announced in A028
base_sha: 461f6f819036f3e9c9a7aa9fa31cf7d54ae83216
code_sha: 461f6f819036f3e9c9a7aa9fa31cf7d54ae83216
tested_sha: 461f6f819036f3e9c9a7aa9fa31cf7d54ae83216
own_saved_checkpoint: e4d726c8afe0ab328bbfe47d0602619ded7ab33e
observed_B_sha: a7715dd95f2a65d0316d27c1587c66cbc5408fdf
fallback_branch: agents/fallback-a-20261024t0114z (create after this publication)

После01:14UTC успешно прочитаны обе рабочие ветки, integration/night и fallback
refs; отдельный ls-remote fallback пуст. B всё ещё a7715dd/B020, новых сообщений,
ACK, commit, ETA или fallback не наблюдается. Сеть работает. Собственное дерево
чистое. Исходный CHECK-IN с23:26UTC и два повтора сохранены; intent опубликован
9df34c8 не позднее00:58:18UTC. 90 минут и отдельные15мин истекли, earliest01:14
достигнут. Это наблюдение Git, не утверждение о смерти процесса/утрате B-WIP.

Включаю только ограниченный fallback по §7 и путям A028. От свежей integration
создам отдельную ветку; собственные проверенные metadata перенесу обычным merge.
Не сбрасываю/не перезаписываю B-ветку или неизвестный локальный WIP другого ПК.
До кода новых контрактов — уникальное временное решение
coordination/decisions/fallback-a-20261024T0114Z-v1.md, явно НЕ ACK B.

Порядок небольших пакетов: F1 конфликт bank ID; F2 восстановление mapping;
F3 история сохранённых расчётов; F4 подтверждение текущего proposal; F5 активация
уже зарегистрированной2.0 с unavailable probability. Только необходимая цепочка
MVP и проверки. Новое обучение/ретюнинг/переписывание frozenlegacy/B7/evaluation
не входят. Каждый пакет — профильные тесты, reviewer, fetch/проверка возврата B,
публикация fallback и PR в integration; квотное исключение прежнее.

Проверять связь между пакетами и примерно каждые10мин. Любая новая B-активность:
прекратить новые пересекающиеся правки, сохранить checkpoint, HANDOFF/RETURN и
явно согласовать продолжение. Не считать старый B020 ответом на новые предложения.
Main по-прежнему только человек; один интегратор A, без force push/расходов/production.

Дополнительный чистый C001 checkpoint сохранён в C001-ACCEPTANCE.md: новый стенд18086,
1131операция, повтор без дублей, все4численных сценария и два ForecastOut SHA после
рестарта postgres/api/worker/web совпали. Пока модель1.0; будущая2.0/миграция ещё не
проверены на этом стенде. Синтетические браузерные данные остаются отдельно на18085.

## A-031 · F1 VERIFIED / F3 WORKING / F2 compatibility gate

UTC: 2026-10-24T01:29:02Z
reply_to: A-030,B-020
type: integrated + verified + working (fallback ACTIVE)
code_sha: 9483d18b56f1a6455b9ce11d67e9407ff8119a23
tested_sha: 9483d18b56f1a6455b9ce11d67e9407ff8119a23
fallback_branch: agents/fallback-a-20261024t0114z

Временное решение опубликовано0082ec3121993cf0aa3609b23ce13ddbf5889045 до кода.
F1 PR32 принят в integration/night9483d18: изменённый bank ID отклоняет файл409,
внутрифайловый конфликт failed preview; обычные повторы/категории/no-ID прежние.
Все проверки источников до ledger/balance writes под account lock. 17 новых тестов,
до фикса15падали. Windows профиль CSV/границ/конфликтов и Ruff passed. Полный Linux:
330passed58.38s; Docker API/worker18085 и6ChromiumE2Epassed24.9s. OpenAPI unchanged.
Независимый reviewer treee4917dd6a63c098a94a3ad3d03c266176a226fa1 ready.

F2 в старом предложении не обратно совместим: drop прежнего unique допускает
несколько mappings, а старое приложение выбирает только по rawSHA; новый NOT NULL
ломает старые вставки без mapping_sha. Независимый reviewer подтвердил. Поэтому
эта миграция к существующему volume не применяется, предложение остаётся отдельным
до совместимого дизайна/решения человека. Никакого обхода через изменённые bytes SHA.

Дальше F3: история сохранённых расчётов по принятому временному forecast-history-v1,
с company/account cursor, nullable legacy job, без enqueue. Потом F4 manual confirm
и F5 фактическая активация зарегистрированной2.0. Чистая математика/B7/evaluation
не перехватываются. Новые данные/вероятности не выдумываются.

Последний успешный fetch: B по-прежнемуa7715dd/B020, единственная fallback-ветка
наша9483d18; новых ACK/ETA/RETURN нет. Состояние процесса на ПК B неизвестно.
При возврате — checkpoint/HANDOFF и согласование, не параллельная работа. A.md
обновляется в agents/a-app; следующий пакет берёт её проверенные metadata обычным
merge. Actions not_run/private, main только человеку. Следующая связь до01:49UTC,
fetch между пакетами/примерно каждые10мин во время fallback.

## A-032 · F3 VERIFIED / F4 WORKING

UTC: 2026-10-24T01:50:10Z
reply_to: A-031,B-020
type: integrated + verified + working (fallback ACTIVE)
code_sha: 3e4d90093df8d84169f06a1a6c14bc8d55d69eab
tested_sha: 3e4d90093df8d84169f06a1a6c14bc8d55d69eab
fallback_branch: agents/fallback-a-20261024t0114z

F3 принят PR33 в integration/night: список истории по компании/счёту, стабильный
cursor и nullable legacy job. Только metadata SQL, без input_snapshot/details;
raiseload запрещает скрытую догрузку. UI открывает base/scenario после reload,
переходит к исходной базе и не создаёт новый job. Вложенный scenario не предлагается.
Изоляция/cursor/SQL guards —21Windows+Linuxhistory tests (Linux7.98s). Полный
Linux350passed62.21s до уточнения SQLпроекции; итоговая профильная проверка выше.
Node24 lint/types/4unit/build, Ruff/OpenAPI passed. Docker18085 все7ChromiumE2E
26.4s; после финальной правки historyE2E passed5.4s. Reviewer итогtree
17c8baa43f27f811b5e945c93623c808d8bf5de3 ready, замечание про JSONB исправлено.

Дальше F4: сегодняшний matcher proposal можно явно подтвердить человеком, с
двумя денежными бюджетами, account exclusive lock, строгим body, CSRF и идемпотентным
повтором. Контракт принят только временным fallback-решением0082ec3; это НЕ ACK B.
Чистый matcher/общие DTO не меняем. Затем F5 фактическая2.0 и сохранение старыхC001.
F2 incompatible mapping migration по-прежнему BLOCKED и не применялась.

Последний успешный fetch перед интеграцией: B a7715dd/B020; единственная fallback
наша3e4d900, новых ACK/ETA/RETURN нет. Процесс другого ПК неизвестен. Возврат B
означает checkpoint/HANDOFF и согласование, не продолжение пересекающихся правок.
Связь между пакетами/примерно10мин, следующий heartbeat до02:10UTC. Actions not_run
по квоте, реальные тестовые дефекты исправляются; private/main права не менялись.

## A-033 · F4 VERIFIED / F5 WORKING

UTC: 2026-10-24T02:02:39Z
reply_to: A-032,B-020
type: integrated + verified + working (fallback ACTIVE)
code_sha: 0d40704e292c27d71cf06a1ba50e04731b829b7e
tested_sha: 0d40704e292c27d71cf06a1ba50e04731b829b7e

F4 PR34 принят в integration/night. Подтверждение сегодняшнего matcher proposal:
strict UUID/minor/extra-forbid, CSRF/company/account, exclusive account lock,
оба бюджета по всем confirmed allocations, повтор confirmedpair идемпотентен.
Прежние candidate/rejected решения не перезаписываются409. UI перед действием
показывает реальные реквизиты операции, допускает частичную сумму. Pure matcher,
общие DTO и миграции не менялись; F4 действует по временному решению0082ec3, НЕ ACK B.

25новых+5прежних профильных Windows tests passed; полный Linux376passed67.69s,
Ruff/OpenAPI22paths/Node24lint/types/Dockerwebbuild passed. Новый чистый Compose
cashcast-e2e-final18087: все8ChromiumE2E32.7s, затем повтор на том жеvolume33.0s.
Reviewer finaltree5a5fc52a0c6291233b145fb8297764841d42643f ready.
Первый старый стенд18085 дал7passed/1failed: новый syntheticрасход нарушал EOD
общейfixture, модель честно исключила историю. Подготовка теста исправлена net0,
продуктовые guards не ослаблены; ATT016. Старый volume сохранён, финальныйE2E18087.

Дальше F5: только DEFAULT_MODEL_VERSION=GUARDED_VERSION уже зарегистрированной2.0,
без ретюнинга/B7/evaluation. Проверить фактические API/worker/UI/C001 и неизменность
двух сохранённых1.0 ForecastOut SHA после upgrade/restart. F2 миграция BLOCKED.
Последний успешный fetch B a7715dd/B020, fallback только наша; новых ACK/ETA/RETURN
нет. Любая Bактивность — checkpoint/HANDOFF. Связь между пакетами/~10мин, следующий
heartbeat до02:22UTC. Actions not_run/private, main одобряет/сливает только человек.

## A-034 · F5 VERIFIED / limited fallback checkpoint / A22 WORKING

UTC: 2026-10-24T02:10:26Z
reply_to: A-033,B-020
type: integrated + verified + working
code_sha: e5972e546e0170556665698f1b7686ed573ab069
tested_sha: e5972e546e0170556665698f1b7686ed573ab069

F5 PR35 принят в integration/night: DEFAULT_MODEL_VERSION=GUARDED_VERSION уже
зарегистрированной2.0. Это единственная продуктовая правка factory; реестр,
frozenlegacy/математика/evaluation не менялись. Полный Windows377passed112.61s,
Linux377passed83.87s; Ruff/OpenAPI22paths unchanged. Docker18087 все8ChromiumE2E
38.6s. Новый HTTPregression доказывает исполнение старого1.0job после upgrade,
scenario1.0 от старой базы и новый2.0run/Noneprobabilities без перезаписи старого.
Reviewer tree63fbacd77156eb5c59b59c28b6da005f5c8f7ed3 ready.

Реальный C00118086:1131операция/повтор бездублей, API/worker/explanations/plan-fact,
все4численных сценария и logout passed. Шесть2.0runs имеют None probabilities и
целочисленный p50. Два1.0 SHA из C001-ACCEPTANCE.md совпали после upgrade и restart;
два2.0 SHA тоже сохранились. Это persistence, не новый backup/restore. Оба будущих
плана123456 — явно синтетические. На этом стенде нет браузерныхfixtures.

F1/F3/F4/F5 ограниченного fallback закрыты проверенными пакетами. F2 несовместимая
mapping migration BLOCKED, не применялась. Новых задач B7/B8matcher/B9/B10 и ретюнинга
не беру. Перехват не объявляю согласованным HANDOFF: B всё ещё не ответил. Сохраняю
опубликованную fallback-ветку для RETURN/сверки, продолжаю собственную A-owned очередь
в agents/a-app: A22 реальное backup/restore актуального демо и восстановление worker/
очереди при отказах. Никаких новых общих контрактов без процедуры согласования.

Свежие remoteB.md/attempts прочитаны: B020/a7715dd, ETA22:56UTC остаётся последней;
новой активности нет, процесс другого ПК неизвестен. До push/betweenpackages/~10мин
проверяем обе ветки/integration/fallback. Возврат — checkpoint/HANDOFF/ACK путей.
GitHub API подтвердил private=True и Actions not_run точныхF3/F4/F5SHA; квоту не
выдаём за доказанную причину server-error без такого сообщения. Применяется ранее
подтверждённое B017 night-ci-quota-v1, реальные дефекты тестов не игнорируются.
Main только человеку. Следующий heartbeat до02:30UTC, продолжаю до09:00МСК.

## A-035 · A22 VERIFIED / A23 API isolation WORKING

UTC: 2026-10-24T02:23:39Z
reply_to: A-034,B-020
code_sha: ae886482c5e81962ba3d957e84cea029fdb3d208
tested_sha: ae886482c5e81962ba3d957e84cea029fdb3d208
type: integrated + verified + working

A22 PR36 принят в integration/night. Четыре restartunless-stopped, migrateпо-прежнему
одноразовый. Актуальный C001pgdump948377байт восстановлен в новой пустой18088БД;
четыре1.0/2.0ForecastOutSHA совпали. Pendingjob восстановился после запуска worker;
internalSIGTERM далавтоперезапуск0→1; второйjob пережил недоступностьPostgreSQL и
после еёвозврата succeeded с теми жеID. Во времяотказаhealth500, worker продолжал
loop с безопаснымOperationalErrortype. Ограничения/manualstop/PID1игнорирование
SIGKILL явно в A22-RESILIENCE.md; не названо полным crash/HAтестом. Дамп внеGit.

Reviewer поправил READMErestore: processenv явно закрепляет project-localPG для
всехтрёхприложений, seedfalse, finallyвозвращает прежние значения. Poisoned-env
negativeconfigtestpassed, внешнихDBзапросовнет. Finaltree991a1cb30f06cc8acf54ca026a9e285ffcddaace
ready. Полныйпродукт377Windows/377Linux/8Chrome изF5 остаётся прежним; YAML/документы
не вызвали бессмысленныйповтор. ДалееA23: проверить fail-closed доступ к legacy jobs
безcompany_id, API isolation и отрицательные сценарии. НовыхсовместныхDTO/Bкода нет.

Bпо-прежнемуa7715dd/B020, новых ACK/ETA/RETURN не наблюдается; опубликованнаяfallback
сохраненаe5972e5. РаботаA23всвоихфайлахa-app. ВозвратB—checkpoint/HANDOFF,без
пересечения. Fetchмеждупакетами/~10мин; heartbeatдо02:43UTC. Actionsnot_run/private,
mainтолькочеловеку. Продолжаю полезнуюочередьдо09:00МСК, F2/B7+честноостаютсянеREADY.

## A-036 · A23 VERIFIED / A24 deterministic retry audit WORKING

UTC: 2026-10-24T02:34:53Z
reply_to: A-035,B-020
code_sha: 2e891e3509cae0737faa08bd32939627a9634462
tested_sha: 2e891e3509cae0737faa08bd32939627a9634462
type: integrated + verified + working

A23 PR37 принят в integration/night. Job без company теперь404 вместо доступного
любойсессии200 с error/runID. Предварительная проверка delay накапливает дату по
каждойцели и отклоняет невозможный календарь422 до enqueue. Frozeninput/математика
и общиеDTO не меняются. До фиксов воспроизведены200/202; reviewer добавил случай
двухпереносов, отдельнаяredрегрессия подтвердила его. Validкрайние даты/нулевой
перенос/разныецели по-прежнему исполняются, база/планы не мутируют. ATT017.

15Windowsпрофильных passed, Ruff/OpenAPI22paths unchanged. ПолныйLinux387passed76.09s;
Docker18087 все8ChromiumE2Epassed33.6s. Reviewer finaltree
4872d0ac7e5d7684db1a48280e782348ea9cc657 ready. Прежний полныйWindows377 изF5 плюс
новыеprofile не названы новымfull387. DraftmainPR19 обновлён до этогоcheckpoint,
с реальными ограничениями/F2/B7+/fallback; draft=True, Approve/merge не выполнялись.

A24 — A-owned очередь: проверить, не расходуют ли retries заведомо постоянные
ошибки UnsupportedModelVersionError/ForecastInputError неизменяемого входа. Временные
ошибки должны сохранять retry/lease, статусjob/run — согласован. Новых HTTPполей,
миграций/общих DTO/Bфайлов не планируется. Продуктовыйфикс только после регрессии.

Последний успешныйfetch: B a7715dd/B020 без новыхACK/ETA/RETURN; fallbacke5972e5
сохранена. Проверки связи между пакетами/~10мин и HANDOFF при возврате остаются.
Actions not_run поquota, private/main прежние. Следующийheartbeat до02:54UTC;
работа продолжается до09:00МСК без бессмысленного повторения уже пройденных тестов.

## A-037 · A24 VERIFIED / expanded review and final demo WORKING

UTC: 2026-10-24T02:51:00Z
reply_to: A-036,B-020
code_sha: 1b70a8df033b42f502d4b9518c0a8664deaaabd1
tested_sha: 1b70a8df033b42f502d4b9518c0a8664deaaabd1
type: integrated + verified + working

A24 PR38 принят в integration/night. Неисправимые ForecastInputError и неизвестная
закреплённая версия завершают forecast job/run в одной транзакции без бессмысленных
retries. Временный сбой и такой же typed error другого kind сохраняют прежний retry.
До фикса3red; после15Windowsпрофильных, полныйLinux391passed78.48s, Ruff/Node24
lint/types. Docker18087 все8ChromiumE2E28.2s и отдельный manualconfirmation2.5s.
Reviewer finaltree9fb75c0d54f22a53f4cc94cdd03082be4b09f415 ready. ATT018: найденная
нестабильность теста была привязкой к first/nth после сортировки одинаковых дат;
теперь проверяется UUID плана. Реальную ошибку не списывали на Actionsquota.

Следующий этап: расширенное независимое ревью текущей серверной сборки, фактический
upgrade C00118086 до A24 с проверкой четырёх неизменных1.0/2.0SHA, актуализация
handoff/матрицы. Исправлять только подтверждённые дефекты; новые sharedконтракты
не объявлять согласованными. B a7715dd/B020 без новых ACK/ETA/RETURN; отдельная
fallbacke5972e5 сохранена, F2 incompatiblemigration не применялась. Дальнейшие
проверки fetch между пакетами/~10мин; при возврате HANDOFF/ACK перед пересечением.
Main без Approve/merge. Продолжаю до09:00МСК; heartbeat до03:11UTC.

## A-038 · expanded review BLOCKED / A25 WORKING

UTC: 2026-10-24T03:00:00Z
reply_to: A-037,B-020
code_sha: 1b70a8df033b42f502d4b9518c0a8664deaaabd1
type: blocked + working

Два независимых ревьюера нашли4проверяемыхдефекта. Общая1b70ещёНЕготова к main:
1. Asyncupload с syncSQL может блокировать ASGIloop и commit другого запроса того
же счёта. Ограниченная2sDBtimeout регрессия дала500 для обоихupload. A-owned фикс:
sync FastAPI endpoints/file.file.read, чтобы SQL/CSV шли вthreadpool без новогоDTO.
2. PATCH суммы paidплана оставляетpaid/remaining>0 и блокирует новыйforecast422;
cancelled→planned сохраняет0. Проверяю консервативные terminalguards и нормализацию
partial→paid при точном закрытии остатка. Без новыхполей/истории/reopenобещаний.
3. 2000планов×50000операций дают100млнmatchingpairs. A-owned PlanFactService должен
проверять отдельный бюджет до matcher, без опасного усечения кандидатов.
4. Snapshot берёт старый EOD, но не прибавляет уже известные факты после его даты.
Исправлю A-owned snapshot с явным предупреждением о расчётном остатке; сам EOD и
математика/реестр/замороженные старыеinput не меняются. Никаких правок Bmatcher.

Точные файлы A25: api/v1/imports.py,obligations.py,planned_events.py; core matching
budget; modules/integration/plan_fact.py; forecasting/snapshot.py (A-owned); новые
API/DB/ASGIрегрессии; specs/README/handoff. Новых общихDTO/миграций/моделей нет.
Старые viewerwrite/noIDfingerprint/finalfailedretry ограничения отдельно triage,
не скрыты и не объявлены решёнными. C00118086 обновлён доA24:4SHA совпали,4сервиса
running/restartunless-stopped. Последний B/a771безновойактивности, процесснеизвестен;
связь проверяю успешнымfetchдоpush/~10мин. Следующийcheckpointдо03:25UTC.

## A-039 · A25 VERIFIED / A26 inherited access and import risks WORKING

UTC: 2026-10-24T03:10:00Z
reply_to: A-038,B-020
code_sha: d0e6d62ec16f486ef4ed716d6bb96a211dfc499e
tested_sha: d0e6d62ec16f486ef4ed716d6bb96a211dfc499e
type: integrated + verified + working

A25 PR39 принят в integration/night. Все4замечания двух независимых review закрыты
на A-ownedграницах; Bматематика/DTO/реестр/legacy не менялись. Полный Linux414passed
89.64s, полный Windows414passed95.92s, Ruff/OpenAPI22pathsunchanged, Docker18087 все8
ChromiumE2E32.1s. Оба reviewer и третий verifier READY точногоtree
5d3391cbe9666c362519af3da191e6661170afa3. Сводка reviews/20261024-expanded.md.

Следующий A26: устранить унаследованные риски в собственных файлах, сначала реальные
регрессии. Viewer присутствует в DB/MeResponse, но сейчас имеет write как owner:
внедрить центральную проверку owner для изменяющих company/object запросов, чтение
viewer сохранить. No-ID fingerprint игнорирует имя контрагента: разные факты с одним
старым ключом нельзя молча пропускать. Сохранить прежние fingerprint/ID/уникальность,
добавить безопасный отказ конфликту payload внутрифайла и перед commit. Без смены
identity/миграции/копирования raw/изменений Bфайлов. Идентичные строки без ID остаются
неразличимыми; банковский ID нужен для надёжной дедупликации, это явно опишем.
Ручной retry окончательно failedjob отдельно не реализован, не имитировать готовность.

B по успешномуfetch всёещёa771/B020, никаких новыхACK/ETA/RETURN; чужойпроцесс/WIP
неизвестны. Fallbacke597сохранена, HANDOFF при возврате; новые sharedконтракты не
объявляю ACK. Actionsnot_run/private/main прежние. Продолжаю до09:00МСК, следующий
heartbeatдо03:30UTC, между пакетами проверка связи/~10мин.

## A-040 · A26 VERIFIED / A27 recoverable failed jobs WORKING

UTC: 2026-10-24T03:21:00Z
reply_to: A-039,B-020
code_sha: ee251aede7cc337d4682490dcac89c42e984f50a
tested_sha: ee251aede7cc337d4682490dcac89c42e984f50a
type: integrated + verified + working

A26 PR40 принят: центральная ownerwrite/viewerread проверяет11изменяющихcompany/
objectпутей,8чтений сохраняются, ownerдругойкомпании независим. No-ID collision
теперь failedpreview/atomic409 безсмены fingerprint/ID; exactrepeat/ручнаякатегория/
EOD/конкурентныйпобедитель проверены. До4red1pass; после30Windowsprofile, Ruff,
OpenAPI22pathsunchanged, fullLinux419passed88.70s, Docker18087 все8Chrome29.2s.
Reviewer READY точногоtree07574f499341cc2656adb963332c2336b21ff1f1. Прежний полный
Windows414/A25 не называем419. Сохранённые результаты18086 после A25 имеют4прежнихSHA.

A27 — оставшийся resiliencegap: после трёх временных сбоев обычный новый POST
возвращаетfailedнавсегда. Планирую bounded recovery существующим HTTP POST без
новогоDTO/ручки/миграции. Только явный повтор owner, только конечныйfailed с
консервативным allowlist временных errorcodes/исчерпанной lease и сохранённымinput.
Те жеjob/runID/model/input; attemptsмонотонны (неreset, защитаfencing), новыйбюджет
3попыток. Permanent/unknownfailed не возобновляются; succeeded/pending/running
не трогаются. Всё атомарно подсуществующимиaccount/job/runlocks; параллельныеPOST
не удваивают бюджет. Сначала negativeAPI/workerрегрессии, безправокBматематики.

КодтолькоAowned jobs/recovery.py и вызов из двух POST forecast/scenario, tests/specs.
Новыхsharedформатов нет. Bвсёещёa771/B020 поуспешномуfetch, новыхACK/ETA/RETURNнет;
новыйfallback нерасширяется. Mainчеловеку, private/quotaправила прежние. Heartbeat
до03:41UTC; проверка связи/~10мин и HANDOFFприRETURN.

## A-041 · A27 VERIFIED / A28 existing API integration WORKING

UTC: 2026-10-24T03:35:00Z
reply_to: A-040,B-020
code_sha: 303f5f30edb422bb58c5f19eaeb4fce423f7fa53
tested_sha: 303f5f30edb422bb58c5f19eaeb4fce423f7fa53
type: integrated + verified + working

A27 PR41 принят. Явный POST owner возобновляет только исчерпанный временныйfailed
и сохранённыйinput. Attemptsмонотонен/max+3, Job→Runlock, fastcheckживогоhandler,
атомарныйrollback, sameIDs/input/model/base. Permanent/unknown/legacyнеповторяются.
23Windowsprofile/Ruff/OpenAPIpassed; fullLinux429passed97.35s; Node24lint/types/
4unit/buildpassed; Docker18087 все8Chrome29.3s. Reviewtree3f7e8860eff8cc34359f3d61a9e5e2c4ca7105c0ready.
НовыйemptyCompose18089: миграции/seed/4сервиса, затем явная syntheticterminalfixture
длябраузерноготеста; не названо реальным сетевым отказом. Cachedfailedhistory→POST
→samejob/run→realworker/chart, attempts4/6. FrozenSHA b68cc11bf0fac953b2cbf018ab164a5dfde028378477540e4cc6b138ccc0669c
до/после совпал. ATT021 отличает обнаруженныйбагпервойреализации и действительныеgates.

A28 — functionalинтеграция existingAPI в минимальномUI бездизайнполировки. После
успешного CSVcommit/плана/сверки/категории автоматически отправить новый обычный
POSTforecast, дождатьсяworker, показатьактуальныйграфик. Старыеinput/resultsне менять;
historyopen/reload/сменаcutoff самиPOSTневызывают, terminalfailed не повторять циклом.
Защитаотдублированияэффектов/обновленийкэша; дата дляновогоплана todayUTC, категория
сохраняет выбранныйсрез. НовыхbackendDTO/общихформатов/моделей/миграцийнет.
Это только изменения черезкабинет: фоновойподпискинавнешниеAPIupdates и математического
инкрементальногорасчёта не обещаем. Утреннийредизайн долженсохранитьэтуинтеграцию.

B/a771/B020 безновыхACK/ETA/RETURN поуспешномуfetch; свойAownedUIкоднепересекается
сB. F2blocked/fallbackpreserved/mainprivate/quotaпрежние. Продолжаю до09:00МСК,
связьмеждупакетами/~10мин, следующийheartbeatдо03:55UTC.

## A-042 · A28 VERIFIED / A29 viewer UI WORKING

UTC: 2026-10-24T03:54:00Z
reply_to: A-041,B-020
code_sha: f3f7a6fc92fb24b32a00bb1c2eb3d587e13832c3
tested_sha: f3f7a6fc92fb24b32a00bb1c2eb3d587e13832c3
type: integrated + verified + working

A28 PR42 принят. Успешные UIimport/plan/category/reconcile запускают ровно один
существующийPOSTforecast. Dateedit/history/reload не запускают его; frozenoutputs
остаются прежними. 9ChromiumE2E35.0s, после финальногоwording ещё2planfact3.7s;
Node24lint/types/4unit/build. Reviewer READY treead8d88892a5ff764216ea152c65bbefecc103759.
Backend не менялся,429Linux97.35s относится кA27. ATT022 сохраняет red/ошибкуfixture.

A29 — минимальный role-awareUI: owner из существующего me.companies разрешает
запись только в выбранной компании; viewer читает историю/операции/планы/сверку/причины,
не видит controls изменяющихPOST/PATCH, автоматическийPOST также отключён. Это не
новая securityграница: серверA26 остаётся авторитетным403. Никаких новыхDTO/миграций/
ролей/зависимостей/дизайнполировки. Реальный браузертест на изолированном18089 с
отдельной testviewerучёткой; продуктовыйseed/C001 не менять. Затем общая приёмка,
актуализация матрицы и расширенное forwardreview перед человеческим main.

Fetch03:54UTC: B/a771/B020 без новой активности; процесс/WIP неизвестны, чужие задачи
не расширяю. Fallbacke597сохранена, HANDOFFприRETURN. Private/quotaправила прежние.
Продолжаю до09:00МСК, следующийheartbeatдо04:14UTC, связьмеждупакетами/~10мин.

## A-043 · A29 role UI VERIFIED / A30 manual state race WORKING

UTC: 2026-10-24T04:09:00Z
reply_to: A-042,B-020
code_sha: 47d2eeaf9232cf712715b958359ffab0d8e418d4
tested_sha: 47d2eeaf9232cf712715b958359ffab0d8e418d4
type: integrated + verified + working

A29PR43 принят. 12Nodeunit/lint/types/build,9Chrome35.7s. Реальныйviewer18089 читает
ledger/plan/history/chart безUIwrites, получает403напрямую; companyrole/выход/вход
изолированы. Reviewer tree9c8980f5cc867e99472bec8f044ce7aa4d412e8a READY.
ДваindependentforwardreviewA26..A29 +thirdverifier того жеtree не нашли новых блокеров;
это статическоеreview, не замена runtime. C00118086 обновлёнA29, четыре полныхSHA
1.0/2.0 совпали,6guardedruns сохраняютprobabilityNone. OriginalC0011131не меняли.

Дополнительный targetedrepeat выявил ещё не устранённую нестабильность ручной сверки:
3/10failed после первой частичной оплаты — открытая карточка второгоproposal теряет
реквизиты. Первое объяснение paging НЕ подтвердилось: конкретная операция наpage1
(16outrows); pagingподдержку теста оставляем какобщуюпредпосылку, не rootcausefix.
Trace сохранён внеGit. Проверяю гипотезу remount при смене revisionqueryKey и
invalidation новогоautoPOST. A30 только AownedUI/querylifecycle/tests/specs, без
математики/DTO/схемы/изменения денежныхправил. До исправления общий кандидат не финальный.

Bпоfetch04:03UTC всёещёa771/B020; процесс/WIP неизвестны, чужихACKневыдумываю.
Fallback/contract/private/quota/main ограничения прежние. Следующийheartbeatдо04:29UTC.
