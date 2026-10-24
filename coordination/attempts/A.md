# Попытки агента A

Этот журнал редактирует только A. Перед задачей читать связанный журнал B на его
удалённой ветке. Неудача не вечный запрет: повтор допустим с записанным обоснованием.

## A-ATT-001: тесты аналитики без PostgreSQL

Статус: причина установлена статически, исполнение не воспроизводилось.
Версия: bootstrap bddde8a.
Факт: backend/tests/conftest.py задаёт autouse миграцию и TRUNCATE; pytest в будущем
tests/analytics также наследует их. pgserver отсутствует в dev dependencies.
Не повторять запуск «чистых unit без БД» в этой структуре без проверки условий.
Повтор обоснован после отделения fixtures либо с отдельной уничтожаемой test DB.
Никогда не подставлять демо/рабочую БД для обхода ошибки.

## Шаблон следующей записи

ID; задача; UTC; code SHA; среда/версии; подход/команда без секретов; наблюдаемый
результат; доказательство; причина (подтверждена/гипотеза); условия повторения;
ссылка на новую попытку. Не вставлять полный шумный лог и содержимое выписок.

## A-ATT-002 · восстановление worker

UTC:2026-10-23T21:47:10Z; исходный код f00d3b5. На выделенной cashcast_test три новые
регрессии воспроизвели: последняя умершая попытка остаётся running; второй worker
захватывает живой handler после lease; terminal job.failed оставляет run.pending.
Все3теста падали до изменения, после добавления row lock/ownership check/reaper и
синхронизации run проходят (плюс параметр последней попытки). Повтор обоснован
исправлением продукта. Полный suite97tests и Ruff passed; реальный Compose проверяется.

## A-ATT-003 · ответ до commit / ASGI scope

UTC:2026-10-23T21:57:25Z. При реальном smoke объединённого B5/registry получено
POST202→немедленныйGETjob404; позже запись появилась и worker успешно завершил её.
Установлено: get_db yield cleanup по умолчанию после response. Детерминированный
ASGI-тест до изменения показал response→commit. Исправлено functionscope во всех
HTTP-потребителях, два теста проверяют commit→response и ошибку commit→500 без секрета.
Нижняя граница FastAPI0.121, lockоставляет0.161.1/все версии неизменными.
Первый uv lock--offline не сработал: metadataalembicнетвcache. Повтор с сетью обоснован
неполным кэшем, обновил только specifier в lock, не пакеты. Общий150pytest/Ruff и
реальный C001smoke+ChromiumE2E проходят. Повтор не скрывает404клиентскимretry.

## A-ATT-004 · входы и DNS после пересоздания API

UTC:2026-10-23T22:09:44Z; исходный код e17b64a. Пять регрессий воспроизвели500на
плохих accountUUID и суммах внеBIGINT; теперь422 доDB. Добавлен календарный/resource
тест, полный156pytest+Ruffpassed. Typed UUID и денежные/seedграницы в OpenAPI.
На реальном rebuild API IPизменился172.30.0.5→.4, nginx продолжилстарыйIPиотдал502;
smokeупалнаhealth, E2Eистёкнаlogin. Причина подтверждена nginxлогом/inspect/getent.
Включён динамический upstreamresolve. После фикса nginx-tpassed; контролируемая
сменаIP172.30.0.3→172.30.255.250 восстановилаhealth без заменыwebконтейнера.
Повтор C001smokeвсе4сценария и ChromiumE2Epassed. Повтор обоснован исправлением
продукта, не клиентским retry/увеличением таймаута. Затронут только freshdemo18083.

## A-ATT-005 · CSV источники и общий бюджет

UTC:2026-10-23T22:48:23Z. Общий822candidate дал3красныеHTTPрегрессии: leading/trailing
tab и quotednewline идентификатора исчезали приstrip. B исправил rawвалидациюa249;
HTTPsource_nameC1/NEL послеотдельного замечания исправлен уA. Дваcapacityтеста
воспроизвели успешныйcommit сверх2000планов/9e15общегоостатка. A016/B020 согласовали
целиковый409до записи, ручныепланы под темжебюджетом. Финальные A7tests23passed,
новыйпараллельныйdistinctimportsтест подтверждает один общий бюджет. Никакого обхода
guard/удалениястарыхпланов. РеальныйDocker3c4edf7 прошёл C1HTTP422 иCSV-32100коп.

## A-ATT-006 · банковский CSV не меняет финансовый смысл

UTC:2026-10-23T22:53:22Z; исходныйparser3c4edf7. Синтетическийprobe внеGit воспроизвёл:
1e9 принят как1900коп, unknowndirection какout, 1.234 округлено123коп, badcodecLookupError.
Это не реальные банковскиеданные. Кандидат строгогоразбора заменяет удалениебукв/Decimal
округление точным целочисленным разбором; unknownvalues становятсяpreviewerrors.
Профильные41tests+реальный pg_blocking_pids тестpreviewlockpassed; общийsuite/reviewer
ещё ожидаются. Повтор исходныхпримеров обоснован исправлением, не новым допущением.

## A-ATT-007 · воспроизводимость браузерных сценариев

UTC:2026-10-23T23:38:21Z; пакетA11, frontend-кандидат после08068e0.
Первый E2E ждал getByLabel exact для select с optiontexts; элемент был в snapshot.
Исправлен locator на getByRole combobox, без увеличения таймаута/продуктового обхода.
Второй прогон дошёл до reduceinflow, но получил delta0: каждый повтор добавлял новые
операции с UUID на теже даты и перезаписывал остатки одного исходного потока.
Реальная модель корректно отметила несверки и исключила такую историю. Причина в
синтетическом сценарии повторного теста, не доказанный баг модели/денежного API.
Исправление fixture: стабильные externalIDs/date/ref и остатки от фиксированного
календарного индекса, повтор не удваивает ledger. Проверка на новом отдельном Compose
cashcast-scenarios-check18084 с новым volume, прежний стенд не очищается.
Следующий повтор обоснован изменённой fixture/чистым окружением. Его успех пока не заявлен.

## A-ATT-008 · точное денежное отображение

UTC:2026-10-23T23:44:36Z; исходный formatter2cb8a25.
Прямой Node probe и unit дофикса воспроизвели 8999999999999999minor→.98RUB вместо.99;
второй тест показал, что unsafeinteger также рисуется как будто точное значение.
Причина: Number/100 перед локализацией. Formatter теперь делит BigInt на целую
рублёвую часть и остаток копеек; знак -0 сохраняет минус для суммы меньше рубля.
Unsafeinteger/NaN/Infinity не выдаются за точную сумму. Backend/JSON неизменны.
Первый запуск unit через системный npm использовал Node22.11 и не прочитал .ts;
это ошибка выбранного runtime, не результат продуктового теста. Повтор на bundled
Node24.19 Windows и точном CI Node24.18.1 Linux:4passed; два дофикса падали поassertion.
Lint/types/build passed. Обоснование повтора — исправленная логика и правильный Node24.

## A-ATT-009 · автосверка при enqueue и устаревшая таблица

UTC:2026-10-24T00:05:16Z; A15-кандидат после589fcfd.
Reviewer нашёлP2: сегодняшний POSTforecast сам пишетautoallocations, но не обновляет
новыеplanfact/plansquery. НовыйChromeE2E на старом18084 воспроизвёл: jobдошёлдо
графика, таблица продолжила0связано/77.77остаток/Ожидается; assertionОплаченупал5s.
ForecastPanel теперь инвалидирует обеqueryprefix послеуспешногоenqueue, сохраняя
свойacceptedjob; дата ввода заблокирована на времяоперации. Новыйtestне делаетreload
илиручнойreconcile. Исправление не меняет серверныеалгоритмы/контракты.
Для доказательстваисправления создаётся свежий cashcast-planfact-check18085: старый
прогон уже подтвердилдокумент на сервере, поэтому его повтор не докажетпереход0→paid.
Исходныйvolumeнеочищается. Lint/types/4unitpassed; новаяDocker/E2Eприёмкаожидается.

## A-ATT-010 · resource guard после тяжёлой сборки

UTC:2026-10-24T00:18:53Z; исходныйкод15bb61f.
На отдельнойcashcast_test созданы реальные50001операция/4001остаток/2001план.
Три регрессии ставят tripwire передmatcher: исходный код доходил до него доguard,
testHTTPполучал500изнамеренногоAssertionError. Это доказательство порядка вызовов,
не утверждение, что обычныйпродукт всегда500. Безtripwire guardсрабатывалбы позже,
послеORM/сопоставления/категоризации, что не защищает от их стоимости.
SQLpreflight проверяет тежеResourceLimits раньше; boundedORM+повторнаяпроверка не
обрезают данные молча. Будущее не считается, POSTforecast проверяетиостатки,
отдельныйplanfact — только используемыеим операции/планы. Послефикса308fullpytest
Windows47.89s+Ruffpassed, включаяпятьновыхреальныхDBпроверок. Linux/Docker/E2E/review
следуют. Это rowguard, не полная production-нагрузочная или memory-безопасность.

Итог A16: Linux 308 passed 47.85s, Ruff/Alembic check passed, OpenAPI без diff;
пересобранные API/worker и 5 Chromium E2E на 18085 passed 19.1s. Reviewer tree
92d3821471d912280f9e3ffceecc7ce49733270b ready. Code 9830988 принят через PR26.

## A-ATT-011 · одинаковые сценарии из двух вкладок

UTC: 2026-10-24T00:32:08Z; исходный код 9830988.
Два настоящих HTTP-запроса на отдельной cashcast_test: первое чтение отсутствующего
run удержано SQL-hook, второе успело commit. Первое вернуло 500/IntegrityError,
второе 202. Это настоящая гонка unique constraint, не намеренный tripwire.
Создание сценария теперь берёт существующий account lock перед поиском/вставкой,
как базовый прогноз. Тест наблюдает либо блокировку PostgreSQL, либо завершение
второго запроса, без предположения о фиксированной скорости. Оба 202, одинаковые
run/job, одна запись каждого и успешный worker после фикса. Профиль 8 tests Windows
passed; Ruff passed. Полный Linux: 309 passed 43.52s. Пересобранные API/worker 18085,
четыре формы сценариев в Chromium: 1 E2E passed 10.3s. Продуктовое дерево рассмотрено
независимым reviewer без блокеров; эта запись с результатами проходит финальную сверку.

## A-ATT-012 · сценарий мог принадлежать другой базе

UTC: 2026-10-24T00:35:26Z; исходный код 3d18ac6.
Две базы одного входа с seed42/99; сценарий первой явно переключён на99. Повтор
тех же changes от второй базы вернул ID сценария первой. Регрессия до фикса упала
по равенству ID: уникальный ключ не учитывал base_forecast_id. Такая дедупликация
ломала принадлежность/парное сравнение. Новые scenario_hash включают ID базы;
старый ключ ищется только с точным base_forecast_id, без переписывания данных.
Две вариации (новый и прежний хеш первой базы) и повтор сохранённого старого run
проверяют lineage, job idempotency, unchanged input/results и численное сравнение.
Windows: 4 профильных теста с concurrency passed, Ruff passed. Полный Linux:
312 passed 45.25s. Пересобранные API/worker 18085, четыре формы сценариев:
1 Chromium E2E passed 10.4s. Продуктовый reviewer tree 6040062 ready; финальные
результаты проверяются отдельно. Схемы/миграции/модель/общий DTO не меняются.

## A-ATT-013 · чтение план-факта смешивало версии

UTC: 2026-10-24T00:51:34Z; исходный код 84d1b1c.
Настоящие GET/POST на cashcast_test: GET удержан после SELECT плана, параллельный
POST подтвердил оплату. Затем GET вернул confirmed10000 и прежний remaining10000
при плане10000. Тест до фикса упал по денежному инварианту, без выдуманной ошибки.
PlanFactService теперь берёт shared account lock при чтении и прежний exclusive
при записи. GET не пишет allocations; несколько читателей совместимы, все штатные
писатели используют account FOR UPDATE. Регрессия наблюдает блокировку PostgreSQL
или окончание writer, не фиксированный sleep; проверяет согласованный before/after.
Профильные Windows-проверки и Ruff passed. Полный Linux: 313 passed 46.97s;
пересобранные API/worker 18085 и 2 профильных Chromium E2E passed 5.1s.
Продуктовый reviewer tree 962ffaf ready; финальные метаданные проходят сверку.
Не новый API/DTO/модель/миграция.

## A-ATT-014 · fallback F1: конфликт банковского источника

UTC: 2026-10-24T01:23:11Z; исходный код461f6f8, временное решение fallback-a-20261024T0114Z-v1.
17 новых регрессий: 15 до фикса провалились, два обычных повтора уже проходили.
Смена даты/суммы/направления/контрагента/назначения при коротком и длинном ID
молча пропускалась; хорошая новая строка и остаток записывались. Конфликт одного
ID внутри файла тоже не блокировал preview; два конкурирующих файла оба commit.
Теперь нормализованный source payload сравнивается под account lock до любых
вставок/остатков/категорий. Ошибка409 transaction_id_conflict атомарна и не содержит
сырья; внутрофайловый конфликт failed preview. Balance/категория исключены из
идентичности, одинаковый факт сохраняет ручную категорию, no-ID fingerprint прежний.
Профиль CSV/границ/новых17tests Windows и Ruff passed. Полный Linux330passed58.38s;
пересобранные API/worker18085 и все6ChromiumE2Epassed24.9s. OpenAPI export21paths,
контракт схем не изменился. Независимое ревью следует. F2 incompatible mapping migration остаётся отдельным
proposal, не применяется к существующим данным. Это не ACK B.

## A-ATT-015 · F3: метаданные истории не должны загружать все снимки

UTC: 2026-10-24T01:50:10Z; пакет3e4d900, временный forecast-history-v1.
Первый endpoint select(ForecastRun,Job.id) не отдавал сырьё в JSON, но ORM всё равно
загружал input_snapshot/details каждой строки. Reviewer нашёл риск limit100 больших
снимков. Исправлено явным load_only11полей с raiseload=True. Новый SQL-listener
проверяет одинSELECT истории без тяжёлых JSONB. Не повторять полную ORM-загрузку
ради metadata; отсутствие сырья в response не проверяет стоимость SELECT.
До endpoint регрессия вернула405; после21history tests Windows+Linuxpassed.
Полный350Linux до уточнения SQL62.21s, итоговый profile21Linux7.98s;7Chrome26.4s,
финальныйhistoryChrome5.4s. Node/Ruff/OpenAPI passed. Reviewer tree17c8baa ready.

## A-ATT-016 · F4: синтетический тест нарушил сверку общей fixture

UTC: 2026-10-24T02:02:39Z; пакет0d40704. Первые8E2Eна18085:7passed, reduce-irregular
delta0. Новая проверка manualconfirm добавила OUT98.76 поверх EOD истории сценария,
не добавив равное поступление. В UI явно показана несверка остатков/исключение
истории; это корректный guard, не основание ослаблять assertions или модель.
Новый testCSV содержит OUT98.76 и отдельный syntheticIN98.76, net0. На чистом18087
все8E2Epassed32.7s и повторно33.0s. Старыйvolume не удалён/не очищен. Не повторять
односторонние записи в общем fixtureсчёте с заранее согласованными остатками;
использовать отдельный счёт/стенд или сбалансированные синтетические движения.
Manual tests проверяют реальные поля операции, split4000+5876=9876, reload/повтор,
параллельные альтернативы/одну пару/auto/manual и rollback. Linux376passed67.69s.

## A-ATT-017 · API: отсутствие tenant и составной календарный перенос

UTC: 2026-10-24T02:34:53Z; пакет2e891e3. Два HTTPнегативных теста до исправления
получили200 для job.company_id=null под любой сессией, включая forecast_run_id и
error_code. Теперь nulltenant —404, UUID не считается полномочием. Обычные задания
с company_id сохраняют прежний доступ; схемы ответа не менялись.

Delay9999-12-31+1 до проверки давал202 для заведомо неисполняемого задания. Первый
фикс проверял каждыйshift от исходнойдаты. Reviewer нашёл составной+1,+1 от9999-12-30;
отдельнаярегрессия снова получила202. Итог хранит накопленнуюдату каждойцели отдельно,
не меняя frozenDTO. Невозможные комбинации422 без job/run; допустимые/нулевые и две
разныецели доходят доsucceeded. Не повторять независимую проверку составных операций,
если worker применяет их последовательно.

Профиль15Windows/Ruff/OpenAPIpassed; fullLinux387passed76.09s и все8Chrome33.6s
наDocker18087. Reviewer tree4872d0ac7e5d7684db1a48280e782348ea9cc657 ready.

## A-ATT-018 · постоянная ошибка и нестабильная строка E2E

UTC: 2026-10-24T02:51:00Z; A24 1b70a8df033b42f502d4b9518c0a8664deaaabd1.
До фикса три регрессии: неизменяемый невалидный вход/неизвестная modelversion
оставляли job pending и расходовали попытки. Старый тест искусственно max_attempts1
скрывал проблему. Теперь permanentpolicy только для forecast и двух точных типов;
transient/инойkind по-прежнему retry. Job/run terminal атомарны с прежними guards.

Первый браузерный прогон7/8: проверка отменённого плана через first() иногда брала
другую строку с той же датой после PATCH. Продуктовая отмена исправно сохранялась.
Не ослаблять assertion и не добавлять sleep: выбрать точный UUID. Итог все8passed
28.2s, затем manualconfirmation повторно2.5s. ПолныйLinux391passed78.48s, Windows
profile15, Ruff/Nodepassed. Reviewer finaltree9fb75c0d54f22a53f4cc94cdd03082be4b09f415.

## A-ATT-019 · расширенное ревью: тесты одного event loop и финансовых границ

UTC:2026-10-24T03:10:00Z; A25d0e6d62ec16f486ef4ed716d6bb96a211dfc499e.
Обычный TestClient/два потока не воспроизводили взаимную блокировку syncSQL async
upload и function-scope cleanup другого запроса. Новая регрессия использует один
ASGIloop, реальный Account lock и внешний observer pg_blocking_pids. Неограниченный
async timeout не спасает заблокированныйloop; отрицательный тест ограничен DB2s.
Первая statementпопытка ошиблась атрибутом session/_session testwrapper, исправлена;
это не доказательство productdefect. После исправления wrapper обаupload реально
дали500 на ожиданииlock; sync endpoints/file.file.read устранили оба.

7plan-regressions воспроизвели invalidstatus/amount/reopen,2noop ужепроходили;
5openingregressions дали старый EOD/потерянный расход/неверный202overflow. Resource
spy подтвердил проход4HTTPпутей в matcher до guard; максимальный100Mнабор не запускали.
Нельзя усекать proposals: это меняет неоднозначность/может разрешить falseauto.
Старые frozeninput не чинятся заднимчислом; новыеopening содержат известные факты,
сам EOD/дата остаются исходными. Все4fixes только Aowned, безBматематики/DTO.
Итог414Linux89.64s/414Windows95.92s/8Chrome32.1s; дваreviewer+thirdverifier tree
5d3391cbe9666c362519af3da191e6661170afa3 READY. Тристарыхриска выделены в reviewотдельно.

## A-ATT-020 · роль по целевой компании и конфликт без смены старого ID

UTC:2026-10-24T03:21:00Z; A26ee251aede7cc337d4682490dcac89c42e984f50a.
Старый viewerPOSTpreview200, разныеименаодногоnoIDkey молча committed/skipped,
дваконкурирующихконфликта обаcommitted. Новыерегрессии4red/1pass это подтвердили.
Не исправлять fingerprintдобавлениемимени/новымhash: повтор старой выписки мог бы
создать новыеоперации. Ключсохранён; sourcepayload сравнивается до любыхвставок и
EODupdates. Внутрифайла failed, сledger409transaction_fingerprint_conflict.
Полностьюидентичные фактыбезID по-прежнему неразличимы — не выдавать это за решённое.

ЦентральнаяCompanyAccessпроверяетцелевуюроль, включаяobject-IDмаршруты. Проверены
11отказовзаписи безпобочныхэффектов,8чтений200 и ownerдругойкомпании201.
30Windowsprofile/Ruff/OpenAPIpassed;419Linux88.70s/8Chrome29.2s. Reviewtree07574f4ready.

## A-ATT-021 · повтор transientfailed и ненужное ожидание живого handler

UTC:2026-10-24T03:35:00Z; A27303f5f30edb422bb58c5f19eaeb4fce423f7fa53.
Первые7API/workerрегрессий4red/3pass показали вечныйfailed дляbase/scenario/lease/
конкурентногоPOST. Recoveryтолькоallowlist/exhausted/frozen/owner, attemptsнеreset.
Перваяреализациябезfastcheck всегда бралаJobFORUPDATE и заставлялаобычный повтор
runningjob ждатьhandler. Новаяограниченная1sDBрегрессия дала500; раннийstatuscheck
устраниложидание. Повторпослеlockперепроверяетусловия, fencingattemptsмонотонен.

23Windowsprofile12.52s,429Linux97.35s, Ruff/OpenAPI, Node4unit/build,8Chrome29.3s.
Настоящий Chromium18089 предварительно открылcachedfailedизhistory. Синтетическое
состояние3исчерпанныхпопытокподготовлено только вновойemptyDB, затемPOST/worker/chart
реальны. Это не названо сетевойаварией; триреальныхraiseConnectionError и lostlease
отдельнопроверены наtestDB. SameIDs/attempt4of6/frozenSHAсовпали, backupC001нетронут.

## A-ATT-022 · автоматический прогноз и подлинная неоднозначность fixture

UTC:2026-10-24T03:54:00Z; A28f3f7a6fc92fb24b32a00bb1c2eb3d587e13832c3.
Новый E2E сначала дал bounded7s timeout: после commit POSTforecast не происходил.
Теперь успешное UIизменение remountверсию с refguard одногоPOST. GETinvalidation,
history/reload/dateedit сами новый расчёт не запускают. Дата импортperiod_end,
план/сверка todayUTC, категория сохраняет срез. 9Chrome35.0s, Node24gatespassed;
финальная правка текста PlanFactPanel дополнительно проверена2Chrome3.7s.

Первый общий E2E дал8/9: старый manualfixture создавал два плана последовательно,
первый уже получал однозначную оплату при новом автоматическомPOST до появления
второго. Это ожидаемая существующая safeautoполитика, не поломка ручной сверки.
Fixture теперь атомарно импортирует оба документа CSV, затем проверяет настоящий
ambiguousслучай с делением одной оплаты4000+5876/reload/без двойного учёта.
Assertions не удалены, sleeps/retries не добавлены. Reviewer READY точного tree
ad8d88892a5ff764216ea152c65bbefecc103759. Backendне менялся,429Linux — A27.

## A-ATT-023 · роли UI и опровергнутая гипотеза pagination

UTC:2026-10-24T04:09:00Z; A2947d2eeaf9232cf712715b958359ffab0d8e418d4.
НастоящийSSR/Vite безDOM/mock сначала6roleassertionsred/1readpass, затем12unitpassed;
lint/types/buildpassed. ОтдельныйChromium18089 подтвердилviewerread/zeroUIwrite/403,
рольownerдругойкомпании иlogout/login. ПервыйhelperзабылbaseURL, затемчиталme до
концаlogin; исправлены тестовыеожидания/comboboxselector, это не productdefects.

ОбщийE2E сначала8/9, после boundedpagingизменения9/9(35.7s). Но расследование не
закончилось: readonlyAPI обнаружилстаруюfailedtargetнаpage1с16outrows, не page2.
Repeat10сretain-on-failure trace дал7pass/3fail после первой оплаты4000. Повторять
идею «платёж был после первых200» безнового evidence нельзя. Симптом — secondproposal
снова свернут/нетpurpose послеклика наreview. Сейчас проверяется revisionquery
transientempty/remount vs automaticforecastinvalidation. Trace/диагностика внеGit,
источникC001 не затронут. Последний зелёный общий прогон не объявляет эту race решённой.

## A-ATT-024 · nativeclick потерян из-за disabled во время pointerdispatch

UTC:2026-10-24T04:20:00Z; A3008a5ea9c2f04d0dd6f4375370d9b6edcc9f3f353.
PlaceholderData сохранилстарыеqueryданные, но2/10сноваfailed; эта гипотезаопровергнута,
правка полностьюотменена. Первая сборка placeholderпопытки также далаTSinferenceerror,
исправленаgenericтолькодлядиагностики и затемотменена вместе с попыткой.

ВременныйDOMobserver+pointercapture показал node2false1968ms→disabledtrue2060ms,
pointerdown2079.1/up2079.4на том же disablednode; clickневозник, затем2204msenabled.
ДваGETplanfact вокруг действия содержалиодинаковыйproposalamt5876/autofalse/link4000.
Значит transientisFetching менялdisabled после actionabilitycheck. Убран disabled
толькос «Проверить предложение»; денежный submit/input по-прежнемузаблокирован.
Тотже10repeat44.6s и общий9Chrome42.9s прошли;13unit/lint/buildpassed. SSRзащищает
отвозвратаdisabled, но сам pointerrace не воспроизводит. Reviewer dc9dd95ready.
Trace/DOMhelper внеGit, instrumentation в E2E удалена; testassertions/retriesнеослаблены.

C001helper сначала ошибочно требовал delta inserted0 отидемпотентногоcommit, который
возвращает сохранённую сводку. Затем предполагал9/30, фактическиperiod_end9/29.
Обе testпредпосылки исправлены:1131UUID до/послесовпали, result.as_of=preview.period_end,
модель2.0/30точек/None и historyбезновогоPOST подтверждены. WholePlaywrightError мог
вывести автоматическийARIAsnapshot синтетическихстрок; диагностическийcatch заменён
накороткое имя/первуюстроку безsnapshot. Продуктовыйлоггерrawданные не печатает.
