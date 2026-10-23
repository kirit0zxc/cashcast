# app-api-v1: счета и пресет выписки

Согласовано A-001 (c709472) / B-002 (ced9dd3), 23.10.2026.
Аддитивный HTTP-контракт без изменения аналитических DTO archive-v1.

- GET /api/v1/companies/{company_id}/accounts → {items:[{id,company_id,name,currency}]}.
  Сессия и членство обязательны; чужая компания 404. Порядок name/id. UUID — строки.
- GET /api/v1/import-presets → {items:[{id,name,mapping}]}.
  Сессия обязательна. participants-v1 задаёт date=operation_date, amount=amount,
  direction=direction, counterparty_name=counterparty_name,
  counterparty_ref=counterparty_inn, purpose=payment_purpose,
  external_id=operation_id, balance=balance_eod, delimiter=;, encoding=utf-8-sig;
  inflow/outflow/currency=null. Внутренние defaults parser не меняются.

Импортируется одна выписка statements/Cxxx.csv в выбранный счёт, а не сводная таблица
разных компаний. Секреты и исходные CSV в Git не публикуются.
