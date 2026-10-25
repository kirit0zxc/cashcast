"""Явные mock-источники без сети, секретов и автоматического расчёта налогов."""

import csv
import io
from dataclasses import dataclass

from app.core.errors import AppError

DEMO_DATE = "2026-10-24"
TAX_COLUMNS = ("id", "tax_name", "amount", "due_date", "available_at", "tax_regime", "status")
OBLIGATION_COLUMNS = ("id", "counterparty_ref", "direction", "amount", "currency", "due_date",
                      "available_at", "kind", "provenance", "tax_regime")
MAX_ROWS = 10_000
MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class SourceDocument:
    external_id: str
    label: str
    document_kind: str
    counterparty: str
    direction: str
    amount: str
    due_date: str
    available_at: str = DEMO_DATE
    kind: str = "obligation"
    category: str | None = None
    tax_regime: str = ""
    input_row: int | None = None


@dataclass(frozen=True)
class SourceBatch:
    provider_id: str
    label: str
    documents: tuple[SourceDocument, ...]
    skipped_settled: int = 0


def demo_bank() -> SourceBatch:
    """Плановые графики, а не банковские факты: в ledger ничего не добавляется."""
    return SourceBatch("bank", "Демо-банк", (
        SourceDocument("loan-01-20261028", "Кредит: тело и проценты, платёж 1", "loan_schedule",
                       "ДЕМО Банк", "out", "45000.00", "2026-10-28", category="loan"),
        SourceDocument("loan-01-20261111", "Кредит: тело и проценты, платёж 2", "loan_schedule",
                       "ДЕМО Банк", "out", "45000.00", "2026-11-11", category="loan"),
        SourceDocument("payroll-20261105", "Зарплатный проект: ожидаемая выплата", "payroll",
                       "ДЕМО Зарплатный проект", "out", "180000.00", "2026-11-05", category="payroll"),
        SourceDocument("order-17", "Неисполненное платёжное поручение №17", "payment_order",
                       "ДЕМО Поставщик оборудования", "out", "65000.00", "2026-10-29", category="purchases"),
    ))


def demo_onec() -> SourceBatch:
    """Счета и отдельные платежи графика договора; суммы не дублируют друг друга."""
    return SourceBatch("onec", "Демо-1С", (
        SourceDocument("invoice-client-41", "Выставленный счёт №41", "customer_invoice",
                       "ДЕМО Клиент А", "in", "300000.00", "2026-10-30", kind="invoice", category="sales"),
        SourceDocument("invoice-supplier-52", "Полученный счёт №52", "supplier_invoice",
                       "ДЕМО Поставщик материалов", "out", "95000.00", "2026-11-02",
                       kind="invoice", category="purchases"),
        SourceDocument("contract-9-advance", "Договор №9: предоплата 30%", "contract_installment",
                       "ДЕМО Клиент Б", "in", "60000.00", "2026-10-27", category="sales"),
        SourceDocument("contract-9-final", "Договор №9: остаток после отсрочки", "contract_installment",
                       "ДЕМО Клиент Б", "in", "140000.00", "2026-11-15", category="sales"),
    ))


def tax_template() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    writer.writerow(TAX_COLUMNS)
    writer.writerow(["tax-usn-2026-q3", "ДЕМО Аванс УСН", "42000.00", "2026-10-28", DEMO_DATE, "УСН", "due"])
    writer.writerow(["tax-vat-2026-q3-1", "ДЕМО НДС: часть обязательства", "18000.00", "2026-11-02",
                     DEMO_DATE, "ОСНО", "due"])
    writer.writerow(["tax-paid-2026", "ДЕМО Уже уплаченный налог", "12000.00", "2026-10-20",
                     DEMO_DATE, "УСН", "paid"])
    return stream.getvalue().encode("utf-8-sig")


def tax_csv(content: bytes) -> SourceBatch:
    """Только наш демонстрационный CSV. Сальдо ЕНС не превращаем в будущий платёж."""
    if len(content) > MAX_BYTES:
        raise AppError(413, "file_too_large", "Файл превышает 10 МиБ")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(422, "invalid_tax_format", "Загрузите демо-CSV налогов в UTF-8 по шаблону") from None
    documents = []
    skipped = 0
    seen = set()
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=";", strict=True)
        header = next(reader, [])
        if len(header) != len(TAX_COLUMNS) or set(header) != set(TAX_COLUMNS):
            raise AppError(422, "invalid_tax_format", "Нужен демо-CSV налогов: скачайте шаблон в кабинете")
        for index, cells in enumerate(reader, start=1):
            if index > MAX_ROWS:
                raise AppError(422, "too_many_rows", "В файле допускается до 10000 строк")
            if len(cells) != len(header):
                raise AppError(422, "invalid_tax_row", f"Строка {reader.line_num}: неверное число колонок")
            if any(len(v) > 1000 or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in v) for v in cells):
                raise AppError(422, "invalid_tax_row", f"Строка {reader.line_num}: недопустимые символы или длина")
            values = dict(zip(header, cells, strict=True))
            identifier = values["id"]
            if not identifier or identifier in seen:
                raise AppError(422, "invalid_tax_id", f"Строка {reader.line_num}: пустой или повторный id")
            seen.add(identifier)
            if values["status"] not in {"due", "paid", "cancelled"}:
                raise AppError(422, "invalid_tax_status", f"Строка {reader.line_num}: статус due, paid или cancelled")
            if values["status"] != "due":
                skipped += 1
                continue
            if not values["tax_name"].strip():
                raise AppError(422, "invalid_tax_row", f"Строка {reader.line_num}: нужно название обязательства")
            documents.append(SourceDocument(
                identifier, values["tax_name"], "tax_obligation", "ФНС (демо-данные)", "out",
                values["amount"], values["due_date"], values["available_at"], "tax", "tax", values["tax_regime"],
                input_row=reader.line_num,
            ))
    except (csv.Error, OverflowError):
        raise AppError(422, "invalid_tax_format", "Не удалось прочитать демо-CSV налогов") from None
    if not documents and not skipped:
        raise AppError(422, "empty_tax_file", "Файл не содержит налоговых обязательств")
    return SourceBatch("tax", "ФНС: демо-файл", tuple(documents), skipped)


def obligations_csv(batch: SourceBatch) -> bytes:
    """Проверка дат и точных денег остаётся в существующем адаптере обязательств."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    writer.writerow(OBLIGATION_COLUMNS)
    for doc in batch.documents:
        writer.writerow([doc.external_id, doc.counterparty, doc.direction, doc.amount, "RUB", doc.due_date,
                         doc.available_at, doc.kind, f"ДЕМО · {batch.label} · {doc.label}", doc.tax_regime])
    return stream.getvalue().encode("utf-8")
