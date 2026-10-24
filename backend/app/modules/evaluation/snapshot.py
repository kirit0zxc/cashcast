"""Замораживаем исходную историю до отправки в очередь; чужие счета недоступны."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.models import Account, BankTransaction, DailyBalance
from app.modules.evaluation.service import CheckpointEvaluation
from app.modules.forecasting.service import DEFAULT_MODEL_VERSION


class EvaluationSnapshot:
    @staticmethod
    def build(session, company_id, body):
        account = session.scalar(select(Account).where(Account.id == body.account_id).with_for_update())
        if account is None or str(account.company_id) != str(company_id):
            raise AppError(404, "not_found", "Счёт не найден")
        if account.currency != "RUB":
            raise AppError(422, "unsupported_currency", "Проверка поддерживает RUB; не меняйте валюту исходных данных")
        if not date(1900, 1, 1) <= body.as_of <= datetime.now(UTC).date():
            raise AppError(422, "invalid_evaluation_period", "Дата среза вне поддерживаемого диапазона")
        end = body.as_of + timedelta(days=body.horizon_days * body.folds)
        if end > datetime.now(UTC).date():
            raise AppError(422, "future_evaluation_truth", "Для оценки нужен прошлый период с фактом")
        transactions = session.scalars(
            select(BankTransaction)
            .where(
                BankTransaction.account_id == account.id,
                BankTransaction.booked_on <= end,
            )
            .order_by(BankTransaction.booked_on, BankTransaction.id)
            .limit(50_001)
        ).all()
        balances = session.scalars(
            select(DailyBalance)
            .where(
                DailyBalance.account_id == account.id,
                DailyBalance.balance_date <= end,
            )
            .order_by(DailyBalance.balance_date)
            .limit(4_001)
        ).all()
        if len(transactions) > 50_000 or len(balances) > 4_000:
            raise AppError(422, "evaluation_resource_limit", "Лимит: 50000 операций и 4000 остатков на счёт")
        if not transactions or not balances:
            raise AppError(422, "evaluation_no_data", "Импортируйте операции и дневные остатки")
        if any(t.currency != "RUB" for t in transactions):
            raise AppError(422, "unsupported_currency", "В счёте смешаны валюты")
        # Последняя наблюдаемая дата нужна даже при заявленной полноте: не дорисовываем будущее.
        # Границу покрытия читаем по ВСЕМУ счёту: выходной внутри выписки допустим.
        # Будущие относительно end строки не попадут в frozen-вход или признаки.
        last_transaction = session.scalar(
            select(func.max(BankTransaction.booked_on)).where(BankTransaction.account_id == account.id)
        )
        last_balance = session.scalar(
            select(func.max(DailyBalance.balance_date)).where(DailyBalance.account_id == account.id)
        )
        last = max(day for day in (last_transaction, last_balance) if day is not None)
        if end > last:
            raise AppError(422, "evaluation_truth_missing", "Конец проверки выходит за последний наблюдаемый день")
        records = [
            {
                "id": str(t.id),
                "account_id": str(account.id),
                "booked_on": str(t.booked_on),
                "amount_minor": t.amount_minor,
                "direction": t.direction,
                "currency": t.currency,
                "counterparty_ref": t.counterparty_ref,
                "counterparty_name": t.counterparty_name,
                "purpose": t.purpose,
                "category": None,
            }
            for t in transactions
        ]
        # Ограничиваем также текст, чтобы frozen payload не стал неограниченным архивом.
        if (
            sum(len(t[key] or "") for t in records for key in ("counterparty_ref", "counterparty_name", "purpose"))
            > 8_000_000
        ):
            raise AppError(422, "evaluation_resource_limit", "Превышен предел текстовых данных")
        dataset = {
            "account_id": str(account.id),
            "transactions": records,
            "balances": [{"date": str(b.balance_date), "balance_minor": b.closing_balance_minor} for b in balances],
        }
        return {
            **dataset,
            "dataset_sha256": CheckpointEvaluation.fingerprint(dataset),
            "model_version": DEFAULT_MODEL_VERSION,
            "config": body.model_dump(mode="json"),
        }
