# Свежая резервная копия и восстановление A31 · 24.10.2026

Продуктовый checkpoint: ede8edcb8ca94a657eeb14e22b0ef8e37511371a,
tree259bbfe032249463ee6909b7519455144b5a68c8. Последующий83681f9 меняет только
собственную координационную память и запись итогового review. Бэкенд идентичен A27.

## Источник и дамп

Авторитетный локальный C001: cashcast-final-acceptance, http://localhost:18086.
Перед копированием повторно прошли realChromium1131sameUUID/oneautoPOST/history/
logout и четыре прежних1.0/2.0 ForecastOutSHA. В источнике только1131операция C001,
13сохранённых успешных расчётов и два явно синтетических тестовых плана.

PostgreSQL16 customdump создан внутри исходного контейнера через pg_dump -Fc,
перенесён бинарно docker cp. PowerShellтекстовый pipeline не использован.
Приватный файл cashcast-a31-20261024.dump хранится у владельца вне Git, рядом с
предыдущим dump и private checkpoint; сам файл/SQL/сырые строки не опубликованы.

- Размер:1013820байт.
- SHA256dump:32fb4e7bf2e727f755c435d9f2d6ea6a74ac615c105558c2b9cb9ae07dd5e023.
- SHA256канонического checkpoint:9307130544ac4c0c546ec29c24bbceb60b9bc32302ddd117843828849a719369.
- Checkpoint содержит SHA полных ForecastOut всех13runs, точных UUID1131операции и
  полного списка двух планов; финансовые строки и sessioncookies в отчёте отсутствуют.

## Отдельная восстановленная копия

Project cashcast-restore-current, http://localhost:18090. До создания проверено
отсутствие его volume; после старта PostgreSQL число publicBASE TABLE было0.
Исходная БД/volume не перезаписывались. pg_restore --exit-on-error --no-owner завершён0.

Для API/worker/migrate явно установлены project-local PostgreSQL URL/user/password/DB,
seedfalse, devcookie и порт18090; внешний URL из processenv не наследовался. Миграции
текущего кода завершились0, все4долгоживущих сервиса запущены, БДhealthy.

Через новую настоящую HTTPсессию на18090 совпал весь checkpoint:
1131точный transactionUUID, все13полных ForecastOutSHA/версии и оба плана. Это проверка
фактического восстановления актуальной копии, отдельно от прежней A22проверки.

## Очередь после восстановления

Только worker копии18090 остановлен. Через настоящий API поставлен новый C001run
на2026-09-30/30дней с уникальным seed932024; GETjob подтвердил pending. После запуска
того же worker задание стало succeeded,30точек, модельseasonal-guarded-2.0-w84,
probabilityNone. Повтор POST вернул прежние job/runID. Все13исходных ForecastOutSHA
ещё раз совпали. Этот дополнительный probe находится только в восстановленной копии;
первоначальное сравнение13runs выполнено до его добавления.

Hostreboot/HA/production/новая сеть/внешнее хранилище этой проверкой не утверждаются.
Исторические controlledDBoutage/SIGTERM/restart/leaseпроверки остаются в A22-RESILIENCE.
Основной C00118086, browser18087 и HoneyForge не останавливали ради faultinjection.

Ранние только наши cashcast-nightcheck18081, cashcast-fresh-demo18083,
cashcast-planfact-check18085 и cashcast-restore-final18088 остановлены, volumes
сохранены. Рабочие текущие адреса: C00118086, E2E18087, onboarding18089, restore18090.
