"""ImportService: preview и commit загрузки выписки. Идемпотентность — центральное требование.

preview: разобрать файл, вернуть статистику и первые строки, ничего не фиксируя в ledger.
commit: записать операции и дневные остатки. Повтор того же файла (тот же sha) не создаёт дубли:
на уровне БД стоит уникальный ключ (account_id, fingerprint) — конфликт игнорируется.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import BankTransaction, DailyBalance, StatementImport
from app.modules.imports.parser import ColumnMapping, ParseResult, parse_statement


@dataclass(frozen=True, slots=True)
class PreviewResult:
    import_id: str
    status: str
    total_rows: int
    error_count: int
    duplicate_in_file: int
    period_start: str | None
    period_end: str | None
    sample_errors: list[dict]
    reused: bool  # True — такой файл уже загружали, вернули существующий импорт


class ImportService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def preview(
        self,
        *,
        company_id: str,
        account_id: str,
        filename: str,
        content: bytes,
        mapping: ColumnMapping,
        uploaded_by: str | None,
    ) -> PreviewResult:
        sha = hashlib.sha256(content).hexdigest()
        # Идемпотентность входа: тот же файл в тот же счёт — возвращаем прежний импорт.
        existing = self._session.scalar(
            select(StatementImport).where(
                StatementImport.account_id == account_id,
                StatementImport.content_sha256 == sha,
            )
        )
        parsed = parse_statement(content, mapping)
        if existing is not None:
            return self._to_preview(existing, parsed, reused=True)

        imp = StatementImport(
            company_id=company_id,
            account_id=account_id,
            uploaded_by=uploaded_by,
            filename=filename,
            content_sha256=sha,
            raw_content=content,
            size_bytes=len(content),
            column_mapping=_mapping_to_dict(mapping),
            status="failed" if not parsed.ok else "previewed",
            stats=_stats(parsed),
            period_start=_period(parsed)[0],
            period_end=_period(parsed)[1],
        )
        self._session.add(imp)
        self._session.flush()
        return self._to_preview(imp, parsed, reused=False)

    def commit(self, *, company_id: str, import_id: str) -> dict:
        imp = self._session.get(StatementImport, import_id)
        if imp is None or str(imp.company_id) != str(company_id):
            raise AppError(404, "not_found", "Импорт не найден")
        if imp.status == "failed":
            raise AppError(409, "import_failed", "Импорт содержит ошибки и не может быть подтверждён")
        if imp.status == "committed":
            # Повторный commit идемпотентен: отдаём сохранённую статистику.
            return {"import_id": str(imp.id), "status": "committed", **imp.stats}

        mapping = _mapping_from_dict(imp.column_mapping)
        parsed = parse_statement(imp.raw_content, mapping)
        if not parsed.ok:
            raise AppError(409, "import_failed", "Импорт содержит ошибки и не может быть подтверждён")

        inserted = self._insert_transactions(imp, parsed)
        self._insert_balances(imp, parsed)

        stats = {**_stats(parsed), "inserted": inserted, "skipped_existing": len(parsed.rows) - inserted}
        imp.status = "committed"
        imp.stats = stats
        imp.committed_at = datetime.now(UTC)
        self._session.flush()
        return {"import_id": str(imp.id), "status": "committed", **stats}

    def _insert_transactions(self, imp: StatementImport, parsed: ParseResult) -> int:
        inserted = 0
        for row in parsed.rows:
            stmt = (
                pg_insert(BankTransaction)
                .values(
                    company_id=imp.company_id,
                    account_id=imp.account_id,
                    import_id=imp.id,
                    source_row=row.source_row,
                    booked_on=row.booked_on,
                    amount_minor=row.amount_minor,
                    direction=row.direction.value,
                    currency=row.currency,
                    counterparty_name=row.counterparty_name,
                    counterparty_ref=row.counterparty_ref,
                    purpose=row.purpose,
                    external_id=row.external_id,
                    fingerprint=row.fingerprint,
                )
                # Повтор по (account_id, fingerprint) — пропускаем: законные дубли не плодим и не теряем.
                .on_conflict_do_nothing(constraint="uq_bank_transaction_account_fp")
                .returning(BankTransaction.id)
            )
            if self._session.execute(stmt).first() is not None:
                inserted += 1
        return inserted

    def _insert_balances(self, imp: StatementImport, parsed: ParseResult) -> None:
        # Берём последний известный остаток за каждую дату (строки идут по возрастанию строки файла).
        by_date = {r.booked_on: r.balance_minor for r in parsed.rows if r.balance_minor is not None}
        for bdate, bal in by_date.items():
            stmt = (
                pg_insert(DailyBalance)
                .values(
                    company_id=imp.company_id,
                    account_id=imp.account_id,
                    balance_date=bdate,
                    closing_balance_minor=bal,
                    source="statement",
                    import_id=imp.id,
                )
                .on_conflict_do_update(
                    constraint="uq_daily_balance_account_date",
                    set_={"closing_balance_minor": bal, "import_id": imp.id},
                )
            )
            self._session.execute(stmt)

    @staticmethod
    def _to_preview(imp: StatementImport, parsed: ParseResult, *, reused: bool) -> PreviewResult:
        start, end = _period(parsed)
        return PreviewResult(
            import_id=str(imp.id),
            status=imp.status,
            total_rows=len(parsed.rows),
            error_count=len(parsed.errors),
            duplicate_in_file=len(parsed.duplicate_rows),
            period_start=start.isoformat() if start else None,
            period_end=end.isoformat() if end else None,
            sample_errors=[
                {"row": e.source_row, "field": e.field, "message": e.message}
                for e in parsed.errors[:20]
            ],
            reused=reused,
        )


def _stats(parsed: ParseResult) -> dict:
    return {
        "total_rows": len(parsed.rows),
        "error_count": len(parsed.errors),
        "duplicate_in_file": len(parsed.duplicate_rows),
    }


def _period(parsed: ParseResult):
    if not parsed.rows:
        return None, None
    dates = [r.booked_on for r in parsed.rows]
    return min(dates), max(dates)


def _mapping_to_dict(m: ColumnMapping) -> dict:
    return {
        "date": m.date,
        "amount": m.amount,
        "inflow": m.inflow,
        "outflow": m.outflow,
        "direction": m.direction,
        "counterparty_name": m.counterparty_name,
        "counterparty_ref": m.counterparty_ref,
        "purpose": m.purpose,
        "external_id": m.external_id,
        "currency": m.currency,
        "balance": m.balance,
        "delimiter": m.delimiter,
        "encoding": m.encoding,
        "direction_in_values": list(m.direction_in_values),
        "default_currency": m.default_currency,
    }


def _mapping_from_dict(d: dict) -> ColumnMapping:
    data = dict(d)
    if "direction_in_values" in data and data["direction_in_values"] is not None:
        data["direction_in_values"] = tuple(data["direction_in_values"])
    return ColumnMapping(**data)
