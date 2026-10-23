# statement-mapping-v1 · предложение A020, ACK B ожидается

## Воспроизведённая проблема

Одни и те же байты CSV сначала загружены с неправильным разделителем, затем с
правильным. Второй preview отвечает error_count=0, но возвращает старые import_id
и status=failed; commit409import_failed. Уникальность только account+rawSHA не даёт
исправить настройки в интерфейсе. Подтверждено отдельным HTTP/PostgreSQL probe.

## Предложение поведения

Схемы запросов/ответов остаются прежними. Идентичность preview:
account_id + content_sha256 + mapping_sha256. Mapping SHA — SHA256 канонического
полного ColumnMapping после заполнения defaults: JSON sort_keys, compact separators,
ensure_ascii=False, UTF-8. Списки сохраняют порядок, явные defaults и пропуски равны.
Это не хеш CSV с добавленным newline и не изменение существующих ledger fingerprints.

- Тот же файл+тот же mapping возвращает прежний import_id/статистику/разбор.
- Иной mapping, пока файл не committed: новый независимый preview/import_id;
  старый failed/previewed сохраняется для аудита, его нельзя молча перезаписывать.
- Файл уже committed с другим mapping: 409statement_mapping_conflict до нового
  preview/commit. Нельзя переинтерпретировать уже импортированный ledger без отдельной
  процедуры коррекции. Тот же committed mapping по-прежнему идемпотентен.
- Два разных preview одного файла могут существовать до commit; account row lock
  при commit проверяет другие committed mapping повторно. Успевает только первый;
  второй получает409, никаких новых операций/изменённых остатков частично.
- Неизвестный company/account/import404; CSRF/session и ресурсные ограничения прежние.

Additive migration: nullable mapping_sha256, backfill из сохранённого column_mapping
через те же defaults/canonicalization, затем NOT NULL и unique(account,rawSHA,mappingSHA)
вместо прежнего unique(account,rawSHA). Старые import_id/raw_content/stats/ledger не
меняются. Downgrade при существовании разных mappings одного файла явно запрещён,
а не удаляет данные ради восстановления старого unique. Не менять pure DTO B.

Обязательные проверки: bad→fixed preview→commit, same defaults dedupe, committed
different mapping409, concurrent distinct mapping commit, ledger/balance rollback,
прежние imports+категории+frozen forecasts, Alembic upgrade/backfill/no drift.

Отдельный возможный конфликт bank external_id с иным содержимым в это решение не
входит: прежняя ledger-идемпотентность требует отдельного согласования/дизайна.
