"""Превью внешнего источника переиспользует атомарный импорт обязательств."""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.models import ObligationImport
from app.modules.external_sources.adapters import SourceBatch, obligations_csv
from app.modules.imports.obligations import ObligationImportService


class ExternalSourceImportService:
    def __init__(self, session: Session):
        self.session = session

    def preview(self, *, company_id: uuid.UUID, account_id: uuid.UUID, user_id: uuid.UUID,
                as_of: date, batch: SourceBatch) -> dict:
        result = ObligationImportService(self.session).preview(
            company_id=company_id, account_id=account_id, user_id=user_id,
            as_of=as_of, source_name=f"external-demo-{batch.provider_id}-v1", content=obligations_csv(batch),
        )
        imp = self.session.get(ObligationImport, uuid.UUID(result["import_id"]))
        assert imp is not None
        if not batch.documents and batch.skipped_settled and imp.errors == [
            {"row": 2, "field": "row", "code": "empty_data"},
        ]:
            # Полностью оплаченный файл корректен: новых обязательств просто нет.
            imp.errors = []
            imp.stats = {**imp.stats, "error_count": 0, "total_rows": 0}
            result["error_count"] = 0
            result["total_rows"] = 0
        docs_by_ref = {f"{account_id}:{imp.source_name}:{d.external_id.strip()}": d for d in batch.documents}
        if not result["reused"]:
            # Дополнительные метаданные исходного документа неизменны при оплатах/правках.
            imp.items = [{**item, "category": docs_by_ref[item["source_ref"]].category,
                          "external_provider": batch.provider_id, "external_mode": "demo",
                          "document_label": docs_by_ref[item["source_ref"]].label,
                          "document_kind": docs_by_ref[item["source_ref"]].document_kind} for item in imp.items]
            self.session.flush()
        # Перестановка пропущенных строк не меняет набор обязательств; номера ошибок
        # берём из загруженного сейчас файла, даже при повторном canonical preview.
        row_numbers = {i + 2: doc.input_row for i, doc in enumerate(batch.documents) if doc.input_row}
        result["sample_errors"] = [{**error, "row": row_numbers.get(error["row"], error["row"])}
                                   for error in imp.errors[:20]]
        return {**result, "provider_id": batch.provider_id, "mode": "demo",
                "skipped_settled": batch.skipped_settled, "preview_truncated": len(imp.items) > 20,
                "documents": [{"source_ref": item["source_ref"], "label": item.get("document_label", "Документ"),
                               "document_kind": item.get("document_kind", "obligation"),
                               "direction": item["direction"], "amount_minor": item["amount_minor"],
                               "due_date": item["due_date"], "available_at": item["available_at"],
                               "category": item.get("category"), "provenance": item["provenance"]}
                              for item in imp.items[:20]]}
