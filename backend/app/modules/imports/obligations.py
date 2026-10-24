"""Атомарный CSV-импорт обязательств поверх чистого адаптера участника B."""

import hashlib
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.models import Account, ObligationImport, PlannedEvent
from app.core.plan_capacity import PlanCapacityPolicy
from app.modules.planning.sources import ObligationImportItem, parse_obligations_csv


class ObligationImportService:
    def __init__(self, session: Session):
        self.session = session

    def preview(self, *, company_id: uuid.UUID, account_id: uuid.UUID, user_id: uuid.UUID,
                source_name: str, as_of: date, content: bytes) -> dict:
        if as_of > datetime.now(UTC).date():
            raise AppError(422, "future_as_of", "Дата среза не может быть позже сегодняшнего дня UTC")
        if not source_name.strip() or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in source_name):
            raise AppError(422, "invalid_source_name", "Нужно непустое имя источника без управляющих символов")
        source_name = source_name.strip()
        self._lock_account(company_id, account_id)
        digest = hashlib.sha256(content).hexdigest()
        existing = self.session.scalar(select(ObligationImport).where(
            ObligationImport.account_id == account_id, ObligationImport.source_name == source_name,
            ObligationImport.content_sha256 == digest, ObligationImport.as_of == as_of,
        ))
        if existing is not None:
            return self._preview_response(existing, reused=True)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise AppError(422, "invalid_encoding", "CSV обязательств должен быть в UTF-8") from None
        parsed = parse_obligations_csv(text, as_of=as_of, source_name=f"{account_id}:{source_name}")
        errors = [asdict(error) for error in parsed.errors]
        # Несколько ошибок в одной строке не увеличивают количество строк файла.
        invalid_rows = {e.row for e in parsed.errors if e.row >= 2}
        imp = ObligationImport(
            company_id=company_id, account_id=account_id, uploaded_by=user_id,
            source_name=source_name, content_sha256=digest, as_of=as_of,
            items=[self._serialize(item) for item in parsed.items], errors=errors,
            stats={"total_rows": len(parsed.items) + len(invalid_rows),
                   "valid_count": len(parsed.items), "error_count": len(errors)},
        )
        self.session.add(imp)
        self.session.flush()
        return self._preview_response(imp, reused=False)

    def commit(self, *, company_id: uuid.UUID, import_id: uuid.UUID) -> dict:
        imp = self.session.get(ObligationImport, import_id)
        if imp is None or imp.company_id != company_id:
            raise AppError(404, "not_found", "Импорт не найден")
        # Общая блокировка с ручной правкой, snapshot и план-фактом защищает и повторы.
        self._lock_account(company_id, imp.account_id)
        self.session.refresh(imp)
        if imp.status == "committed":
            return self._commit_response(imp)
        if imp.errors:
            raise AppError(422, "invalid_import", "Сначала исправьте все ошибки CSV; частичный импорт запрещён")

        references = [item["source_ref"] for item in imp.items]
        existing = {e.source_ref: e for e in self.session.scalars(select(PlannedEvent).where(
            PlannedEvent.company_id == company_id, PlannedEvent.source == "csv",
            PlannedEvent.source_ref.in_(references),
        ))}
        # Сначала проверяем весь набор. Конфликт не оставляет даже первые новые документы.
        for item in imp.items:
            previous = existing.get(item["source_ref"])
            if previous is not None and previous.source_payload != item:
                raise AppError(409, "SOURCE_ID_CONFLICT", "Внешний ID уже связан с другим исходным документом")

        additions = [item for item in imp.items if item["source_ref"] not in existing]
        PlanCapacityPolicy(self.session).ensure_change(
            imp.account_id, added_count=len(additions),
            remaining_delta=sum(item["amount_minor"] for item in additions),
        )

        inserted = 0
        for item in imp.items:
            if item["source_ref"] in existing:
                continue
            self.session.add(PlannedEvent(
                company_id=company_id, account_id=imp.account_id, direction=item["direction"],
                amount_minor=item["amount_minor"], remaining_amount_minor=item["amount_minor"],
                currency=item["currency"], due_date=date.fromisoformat(item["due_date"]),
                available_at=datetime.combine(date.fromisoformat(item["available_at"]), time.min, UTC),
                kind=item["kind"], status="planned", source="csv", source_ref=item["source_ref"],
                counterparty_ref=item["counterparty_ref"], provenance=item["provenance"],
                tax_regime=item["tax_regime"], source_payload=item, created_by=imp.uploaded_by,
                category=item.get("category"),
            ))
            inserted += 1
        imp.status = "committed"
        imp.committed_at = datetime.now(UTC)
        imp.stats = {**imp.stats, "inserted": inserted, "skipped_existing": len(imp.items) - inserted}
        self.session.flush()
        return self._commit_response(imp)

    def _lock_account(self, company_id: uuid.UUID, account_id: uuid.UUID) -> Account:
        account = self.session.scalar(select(Account).where(
            Account.id == account_id, Account.company_id == company_id,
        ).with_for_update())
        if account is None:
            raise AppError(404, "not_found", "Счёт не найден")
        if account.currency != "RUB":
            raise AppError(422, "unsupported_currency", "Импорт обязательств поддерживает только RUB")
        return account

    @staticmethod
    def _serialize(item: ObligationImportItem) -> dict:
        event = item.event
        return {"source_ref": item.source_ref, "direction": event.direction.value,
                "amount_minor": event.amount_minor, "currency": item.currency,
                "due_date": event.due_date.isoformat(), "available_at": event.available_at.isoformat(),
                "kind": event.kind, "counterparty_ref": event.counterparty_ref,
                "provenance": item.provenance, "tax_regime": item.tax_regime}

    @staticmethod
    def _preview_response(imp: ObligationImport, *, reused: bool) -> dict:
        return {"import_id": str(imp.id), "status": imp.status, "source_name": imp.source_name,
                "as_of": imp.as_of, "total_rows": imp.stats["total_rows"],
                "valid_count": imp.stats["valid_count"], "error_count": imp.stats["error_count"],
                "sample_errors": imp.errors[:20], "reused": reused}

    @staticmethod
    def _commit_response(imp: ObligationImport) -> dict:
        return {"import_id": str(imp.id), "status": "committed",
                "inserted": imp.stats["inserted"], "skipped_existing": imp.stats["skipped_existing"]}
