# A22 · актуальная копия БД, восстановление и отказы сервисов

Checkpoint: 2026-10-24T02:18:36Z. Продуктовая базаe5972e5/F5, собственные metadatae74bf3c.
Единственная новая runtime-конфигурация — restartunless-stopped у postgres/api/worker/web;
migrate остаётся restartno. Точный принятый tree/code записывается в A.md после ревью.

## Backup и отдельная восстановленная БД

Источник: cashcast-final-acceptance18086, C0011131операция и явно синтетические планы
из C001-ACCEPTANCE.md. pg_dump16 custom format(-Fc) внутри postgres, затем dockercp
сохраняет бинарные байты без PowerShell-перенаправления. Размер948377байт, SHA256:
2603334c6716e05450ae65ec25713ebb566a1d4e71517b4e3409d710793a39be.
Дамп содержит данные приложения/сессии, находится в private-backups вне репозитория.
Не загружен в GitHub и не включён в PR.

Новый project cashcast-restore-final, новый volume cashcast-restore-final_pgdata,
отдельная сеть и только loopbackweb18088. До pg_restore проверено0publictables;
восстановление --exit-on-error --no-owner в пустую БД прошло. Затем подняты штатные
API/worker/web/migrate; migrateExited0, postgreshealthy. Исходныйvolume не очищался
и не использовался для тестового TRUNCATE/restore.

Через новую HTTPсессию18088 совпали полные канонические ForecastOut SHA четырёх
run из C001-ACCEPTANCE: два1.0 и два2.0, без изменения model/data/version/points.
Это реальная проверка restore, отдельно от прежних restart-only доказательств.

## Очередь и доступность

1. При остановленном worker через API поставлен новый30дневныйC001прогноз seed888001.
   Job e836713b-bed7-4de9-84f5-534e0547420b реальноpending. После запуска исполнителя
   он сталsucceeded,30точек; повтор идентичногоPOST вернул те же job/runID.
2. Worker был запущен со штатным handler сигналов; внутренний SIGTERM завершил
   процесс. Docker с новой политикой сам поднял его: RestartCount0→1 и новый
   StartedAt/workerid. Это проверка перезапуска после завершения процесса, не
   утверждение об исчерпывающей проверке всех SIGKILL/mid-handler/host-power сценариев.
3. Отдельный seed888002 поставлен при остановленном worker: job
   a67d8a4d-3d00-47b5-bffb-72fb34cf3fd6 pending. PostgreSQL остановлена, worker запущен
   без БД. В логах только OperationalError type; процесс продолжал работать без
   restartloop. Health в этот период500, доступность не объявлялась зелёной.
4. После start PostgreSQL тот же worker автоматически обработал прежнийjob:
   succeeded/30точек; повторPOST вернул прежниеID. Все четыре сохранённых ForecastOut
   SHA вновь совпали. Оба новых probeрасчёта живут только в восстановленной копии.

Ручные dockerstop/docker kill намеренно останавливают контейнер и подавляют
автоперезапуск до явногоstart — это поведение Docker, а не доказательство ошибки
политики. СигналSIGKILL изнутри PIDnamespace init может игнорироваться; такой опыт
не записан как успешный crash-тест. Проверка выше использовала установленный SIGTERM
handler после подтверждённого workerstarted.

Существующие PostgreSQLрегрессии test_worker_recovery.py/test_queue.py отдельно
проверяют истёкший lease, последнюю потерянную попытку, rowlockживого handler и
исчерпание retries. Их полный checkpoint:377Windows/377Linux в F5. Новый YAML не
меняет код очереди/lease или HTTPконтракты; тесты ради YAML-снимка не дублируются.

Все faultinjection выполнены только на restored18088. ОсновнойC00118086 и браузерный
18087 не останавливались. Linux/Windowshostreboot, production/HA и внешнее резервное
хранилище не проверялись и не объявляются реализованными.

## Правка инструкции по ревью

Одного нового project name недостаточно, если внешний CC_DATABASE_URL наследуется
из окружения/.env: пустая локальная БД и приложение могли иметь разные адреса.
README теперь явно задаёт все POSTGRES-параметры и внутреннийURL для API/worker/
migrate, seedfalse, локальныйпорт/devcookie; в finally возвращает прежние processenv.
Отдельная негативная проверка с унаследованным invalid.invalid:1 URL показала через
dockercomposeconfigJSON, что все три сервиса используют project-local postgres,
seed выключен, после finally прежний env восстановлен. Внешних DBзапросов не было.
