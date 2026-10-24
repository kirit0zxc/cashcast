# Утренний frontend: подключение к настоящему CashCast

Это описание уже реализованных ручек, а не новый контракт. Машинные типы и поля:
[openapi.json](openapi.json), бизнес-правила [api.md](api.md). Точный проверенный SHA,
активная версия модели и стенд — coordination/A.md; main ночью не обновляется.
Изменения оформления можно делать отдельно, сохраняя эти правила интеграции.

## Запуск и сессия

Один Compose по README поднимает nginx/web, FastAPI, worker и PostgreSQL. Браузер
обращается к `/api/v1` на том же origin; отдельный публичный адрес БД не нужен.
Локальный демо-вход указан в README. Vite dev proxy требует отдельно запущенный API;
готовый Docker-стенд не требует Node/Python на компьютере пользователя.

1. `POST /auth/login` с `{email,password}` ставит HttpOnly `cc_session` и доступную
   JavaScript cookie `cc_csrf` (без HttpOnly), возвращает
   `{id,email,csrf_token,companies:[{id,name,role}]}`.
2. После reload `GET /auth/me` восстанавливает пользователя/компании/CSRF.
3. POST/PATCH передают `X-CSRF-Token` из ответа и cookies, `credentials:same-origin`.
   Для multipart не задавать Content-Type вручную: браузеру нужен boundary.
4. `POST /auth/logout` →204 без JSON. После смены пользователя очищать query-cache
   и локальное состояние всех компаний/счетов. Токены не писать в localStorage/логи.

401 — сессии нет/истекла, 403csrf_failed — неверный CSRF, чужая сущность404.
Общая ошибка `{error:{code,message,field_errors,request_id}}`; тело ошибки не `detail`.
UI должен показывать сообщение и возможность исправить ввод/войти повторно.

## Счёт и импорт

`GET /companies/{company}/accounts` →`{items:[{id,company_id,name,currency}]}`.
UUID счёта обязателен для выписки/прогноза; нельзя подменять его названием/индексом.
При смене компании/счёта сбрасывать preview, курсоры, job и выбранный прогноз.

`GET /import-presets` отдаёт participants-v1: UTF-8 BOM, `;`, русские направления,
ИНН как строка. Пользователь выбирает одну `statements/Cxxx.csv`. Сводный файл с
теми же операциями нельзя добавлять как ещё один независимый источник.

`POST /companies/{company}/imports`: multipart `account_id`, `file`, `mapping`
(JSON-строка объекта пресета). Preview содержит import_id/status/total_rows/error_count/
sample_errors/period_start/period_end/reused. Кнопка commit недоступна при errors.
`POST /imports/{id}/commit` →статистика inserted/skipped_existing. Повтор возвращает
первоначальную статистику, а не число новых строк этого HTTP-запроса.

Известный незакрытый дефект: исправленный mapping тех же байтов после failedpreview
пока возвращает старый import. Решение statement-mapping-v1 предложено A020, ACK и
реализация ожидаются. Не обходить это изменением байтов/ID на фронтенде.

Счета/обязательства — отдельный поток: `POST /companies/{company}/obligation-imports`
с file/account_id/source_name/as_of; после preview без ошибок —
`POST /obligation-imports/{id}/commit`. Шаблон: evaluation/examples/obligations-demo.csv.
Конфликт изменённого sourceID409SOURCE_ID_CONFLICT откатывает весь набор.
Источник/provenance/tax_regime — данные документа, не подтверждение налоговой проверки.

## Данные и план-факт

`GET /companies/{company}/transactions?account_id=...&limit=25&cursor=...`
→`{items,next_cursor}`. Курсор непрозрачный, следующая страница использует его целиком.
`PATCH /transactions/{id}/category` принимает значение Category из OpenAPI; ручная
категория сохраняется при повторном импорте/автокатегоризации.

`GET/POST /companies/{company}/planned-events` — список/новый план; PATCH по
`/planned-events/{id}` меняет дату, сумму или статус. Список компании содержит разные
счета: отображать только выбранный account_id. В UI уже есть создание/CSV/отмена.
У плана показывать исходную сумму, remaining_amount_minor, статус и источник.
Отмена не удаляет документ и не возрождается при идентичном CSV-reimport.

`GET /companies/{company}/plan-fact?account_id=...&as_of=YYYY-MM-DD` только читает:
items[{event,confirmed_amount_minor}], confirmed_matches и proposals. Proposal может
быть альтернативой другому, суммы альтернатив нельзя складывать и считать оплатой.
`POST` на тот же URL применяет только безопасные auto-confirm на сегодняUTC.
Минимальный UI уже показывает связанные суммы, остатки, просрочку, предложения и
подтверждённые связи; отдельная кнопка вызывает этот безопасный POST.
Ручное подтверждение неоднозначной пары пока не реализовано; draft plan-fact-confirm-v1
ждёт ACK A017. Нельзя рисовать такой запрос как доступную кнопку с мнимым успехом.

Историческое состояние планов ещё не версионируется полностью. Сервер может вернуть
409historical_plan_unavailable; POST historical reconcile запрещён. Сегодняшний ввод
плана не должен незаметно становиться известным в старом прогнозе.

## Прогноз и четыре сценария

`POST /companies/{company}/forecasts` с account_id/as_of/horizon_days(1–180)/seed?
→202 `{job_id,forecast_run_id,status}`. Затем опрос `/jobs/{job_id}` до succeeded/failed.
При failed показывать error_code; не опрашивать бесконечно. После succeeded читать
`GET /forecasts/{forecast_run_id}` и `/explanations`. Ответ фиксируется до отправки202;
немедленный GET не должен требовать маскирующий404 retry.

Forecast — сохранённый снимок с model_version/data_version/seed, points и risk.
Идентичный запрос возвращает прежний run, изменившийся вход — новый. Список истории
пока не реализован (draft forecast-history-v1, ACK A017 ожидается); известный ID можно
читать после reload. Не создавать новый расчёт вместо открытия сохранённого.

Сценарий: `POST /forecasts/{baseId}/scenarios` с `{changes:[...]}` →такой же asyncflow.
Четыре вида: add_expense(amount_minor,on_date), delay_event(target_id,shift_days),
reduce_irregular_inflow(factor0…1), increase_recurring(target_id?,factor1…2).
Проценты в UI переводятся в factor; money — в целые копейки до отправки.
Цели принадлежат frozenbase: prototype берёт planned-in и recurrence-out из её
explanations/source_ref/detail, а не из сегодняшнего списка изменённых планов.
Если подходящей цели нет, объяснить это и предложить новую базу; не придумывать ID.

`GET /forecasts/{scenarioId}/comparison` отдаёт base/scenario p50 и delta по дням,
оба risk. База неизменна; scenario не записывает реальные оплаты. Вложенный scenario
и сравнение разных seed/моделей/входов дают409. После изменения формы убирать старое
сравнение, на время задания блокировать повторную отправку. Все4формы уже работают.

## Как честно показывать числа

Все *_minor — целые копейки, RUB; форматировать через shared/money.ts. Number/100
может терять копейку на верхней границе, formatter использует BigInt и проверяет safeint.
Неизвестная сумма/вероятность отличается от нуля. Probability null →«недоступна»,
0 →0%. risk.available=false не обнуляет существующие p50-даты/дефицит.

У зарегистрированной2.0 вероятность нового разрыва не подтверждена и скрыта(None).
Её активация default ожидает отдельного BREADY; старые1.0 snapshots сохраняют свою
версию. p10/p90 — эмпирические траектории модели, не доказанная банковская гарантия.
Допущения/data_warnings и provenance должны оставаться видимыми после редизайна.

## Что сохраняют тесты

`npm run test:unit` на Node24 проверяет денежные границы. Chromium E2E на отдельном
Compose проверяют вход/ошибку пароля/CSV/прогноз/выход, планы/CSV/cancel/reimport и
четыре численных сценария/immutablebase. Эти сценарии нужно сохранить при редизайне.
Это интеграционные проверки, не оценка качества модели на настоящих банковских данных.
