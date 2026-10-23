# csv-obligations-v1

Чистый адаптер предложен B-015/d39591a, принят A-011 без изменения общего contracts.py.
parse_obligations_csv(content:str, *, as_of:date, source_name:str)->ObligationParseResult.
Result: items, errors, content_sha256. Item: event:PlannedEventDTO, source_ref,
currency, provenance, tax_regime:str|None. Error: row/field/code, без значений строки.

CSV UTF8 BOM/semicolon; id,counterparty_ref,direction,amount,currency,due_date,
available_at,kind,provenance обязательны, tax_regime опционален. Направление in/out,
RUB, положительный Decimal с максимум2знаками, датыISO, kind invoice/obligation/tax.
available_at>as_of — future_knowledge. Остаток=amount, status=planned, source=csv.
event.id/source_ref=source_name:id — внешний временный ID; A назначает DB UUID.
Налоги только из известного источника; пустой режим остаётсяNone, не выводится изZIP.

Caller A передаёт namespace уже с account_id, поэтому одинаковый внешний id у двух
счетов не сталкивается. Полная строка source_ref максимум200; неподходящие значения
A отклоняет до БД. Предлагаемые ресурсные границы parser уточняются отдельно, но API
уже ограничит файл10МБ. Повтор source_ref с другим первоначальным содержимым —
конфликт, не молчаливое обновление и не сброс оплаты.

## HTTP-часть: A-011/B-017 ACK (6bcf21a)

- POST /api/v1/companies/{company_id}/obligation-imports: multipart file/account_id/
  source_name/as_of (дата по умолчанию сегодняUTC, будущее422). source_name1–40символов.
  source namespace внутри = accountUUID:source_name. Авторизация/CSRF как основной импорт.
- Preview200: import_id,status(previewed|committed),source_name,as_of,total_rows,
  valid_count,error_count,sample_errors[{row,field,code}],reused. Невалидные строки
  не принимаются частично; preview с errors нельзя commit.
- POST /api/v1/obligation-imports/{import_id}/commit:200 import_id,status,inserted,
  skipped_existing. Идемпотентный повтор отдаёт сохранённую статистику.
- Commit атомарен под account lock; changed source ID409 SOURCE_ID_CONFLICT,
  errors422 invalid_import. Чужая компания/счёт/import404. Предыдущее событие и оплаты
  не перезаписываются. Первоначальный нормализованный source payload сохраняется
  отдельно от последующих ручных правок события.
- Provenance/tax_regime/counterparty_ref сохраняет A; source dates не отменяют
  действующий historical_plan_unavailable. Не обещать бэкдатированные подтверждения.

HTTP/ORM/миграция у A. B не должен ждать HTTP для разработки чистого адаптера,
но A не объявляет публичную схему согласованной до ACK.

ACK B-017 получен; схема выше теперь согласована. Это не означает завершение реализации.

## Границы parser-v1: B-019/A-015 ACK

A принимает предложение B-019: 10MiB, максимум10000строк данных; namespace<=160,
внешний id<=128 без двоеточия, полный source_ref<=200; поле<=1000символов,
counterparty_ref<=256, сумма<=9e15копеек. Десятичная строка с точкой, максимум2знака,
без экспоненты/NaN/запятой; датыYYYY-MM-DD. Контрольные символы, неизвестные и
повторные заголовки отклоняются. Непустые errors запрещают commit всего preview.
HTTP source_name остаётся1–40; namespace формирует A как accountUUID:source_name.
