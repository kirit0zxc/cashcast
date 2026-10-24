"""«Финансовый пульс»: один связный отчёт для предпринимателя по выписке одного счёта.

Три вопроса и общий список действий:
- cash    — «Когда может не хватить денег» (предупреждение и план, cashcast-advisor);
- money   — «Где вы теряете деньги» (аудитор расходов, cashcast-leaks);
- clients — «От кого вы зависите» (рейтинг клиентов и стресс-тест, cashcast-advisor);
- actions — что сделать, по срочности и сумме.

Модули согласуются между собой, а не просто лежат рядом:
- если впереди возможная нехватка, совет «разместите свободный остаток» откладывается;
- проценты за овердрафт показываются как цена прошлых разрывов (дни в минусе за год);
- клиент с ранним сигналом ухода попадает в срочные действия, если от него зависит выручка.

Все суммы — целые копейки. Только данные до as_of. Без внешних зависимостей.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Literal

from .advisor.baseline_curve import BaseCurve, build_base_curve
from .advisor.client_stress import describe, stress_clients
from .advisor.counterparties import rate_counterparties
from .advisor.dataset import Operation
from .advisor.rescue import PlannerConfig, plan_rescue
from .leaks.model import rub
from .leaks.quality import drop_export_duplicates
from .leaks.report import build_report

METHOD_VERSION = "pulse-0.1"
Status = Literal["ok", "watch", "risk", "unknown"]
Urgency = Literal["now", "this_month", "later"]
_STATUS_RANK = {"unknown": 0, "ok": 1, "watch": 2, "risk": 3}
_URGENCY_RANK = {"now": 0, "this_month": 1, "later": 2}


@dataclass(frozen=True, slots=True)
class PulseConfig:
    warn_days: int = 30  # «скоро» — в пределах 30 дней, как в кейсе
    top_actions: int = 5
    client_min_share: float = 0.05
    money_watch_minor: int = 5_000_000  # блок «деньги» тревожит от 50 тыс. ₽ потерь за год


@dataclass(slots=True)
class Action:
    urgency: Urgency
    title: str
    why: str
    amount_minor: int  # сколько денег за этим действием (0 — если не про деньги)
    source: Literal["cash", "money", "clients"]


@dataclass(slots=True)
class PulseReport:
    company_id: str
    as_of: date
    method_version: str
    status: Status  # худший из трёх блоков
    headline: str
    cash: dict
    money: dict
    clients: dict
    actions: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _negative_days(ops: Sequence[Operation], start: date, end: date, balances=None) -> int:
    days = {
        op.op_date: op.balance_eod_minor for op in ops if start < op.op_date <= end and op.balance_eod_minor is not None
    }
    if balances is not None:
        days = {d: v for d, v in balances.items() if start < d <= end}
    return sum(1 for v in days.values() if v is not None and v < 0)


def _cash_block(ops, company_id, as_of, buffer_minor, cfg, stress, curve=None,
                cash_available=True, cash_reliable=True):
    curve = curve if curve is not None else build_base_curve(ops, company_id, as_of)
    plan = plan_rescue(curve, ops, PlannerConfig(buffer_minor=buffer_minor, display_days=curve.horizon_days))
    warn = plan.base_if_owner_withdraws or plan.base
    soon = as_of + timedelta(days=cfg.warn_days)
    gap = warn["first_gap_date"]
    gap_soon = gap is not None and gap <= soon
    below_soon = warn["first_below_buffer_date"] is not None and warn["first_below_buffer_date"] <= soon
    fragile = [s for s in stress.scenarios if s.creates_gap and s.first_gap_date and s.first_gap_date <= soon]
    if not cash_available or not curve.flows:
        status: Status = "unknown"
    elif gap_soon:
        status = "risk"
    elif below_soon or fragile or gap is not None:
        status = "watch"
    elif not cash_reliable:
        status = "unknown"
    else:
        status = "ok"

    only_if_owner = plan.base_if_owner_withdraws is not None and plan.base["first_gap_date"] is None and gap is not None
    best = next((v for v in plan.variants if v.resolved), plan.variants[-1] if plan.variants else None)
    credit = next((a for a in best.actions if a.kind == "credit"), None) if best else None
    if status == "unknown":
        message = ("По сохранённой медиане минус не выявлен, но пригодной истории или актуального "
                   "согласованного остатка недостаточно, чтобы исключить кассовый разрыв."
                   if cash_available and curve.flows and not cash_reliable else
                   "Недостаточно данных для прогноза остатка.")
    elif gap is not None:
        message = f"Возможная нехватка денег {gap:%d.%m}: не хватит до {rub(warn['max_deficit_minor'])}" + (
            " — если выводить деньги из бизнеса как обычно." if only_if_owner else "."
        )
    elif fragile:
        message = describe(fragile[0])
    elif below_soon:
        message = (
            f"Остаток опустится ниже безопасного запаса {rub(plan.buffer_minor)} "
            f"{warn['first_below_buffer_date']:%d.%m}."
        )
    else:
        message = f"По сохранённой медиане на {cfg.warn_days} дней нехватка денег не ожидается."

    return {
        "status": status,
        "message": message,
        "first_gap_date": gap,
        "days_until_gap": (gap - as_of).days if gap else None,
        "max_deficit_minor": warn["max_deficit_minor"],
        "gap_only_if_owner_withdraws": only_if_owner,
        "structural_shortfall": plan.structural_shortfall,
        "buffer_minor": plan.buffer_minor,
        "buffer_source": plan.buffer_source,
        "plan": None
        if best is None or status == "unknown"
        else {
            "title": best.title,
            "resolved": best.resolved,
            "steps": [
                {"title": a.title, "amount_minor": a.amount_minor, "cost_minor": a.cost_minor, "details": a.details}
                for a in best.actions
            ],
            "credit_minor": credit.amount_minor if credit else 0,
            "credit_cost_minor": credit.cost_minor if credit else 0,
            "holds_if_inflows_drop_20pct": best.stress_holds,
        },
        "suggestions": [{"title": s.title, "details": s.details} for s in plan.suggestions],
        "chart": {
            "days": plan.days_display,
            "base_minor": plan.base_balances_display_minor,
            "if_owner_withdraws_minor": plan.base_if_owner_withdraws_display_minor,
            "after_plan_minor": best.balances_display_minor if best else None,
            "buffer_minor": plan.buffer_minor,
        },
        "warnings": plan.warnings,
        "assumptions": plan.assumptions,
        "_plan": plan,  # служебное для сборки действий; в ответ не попадает
    }


def _money_block(ops, company_id, as_of, industry, cash, *, ledger=False, balances=None):
    # Справочник построен на полном датасете: историческому срезу он ещё неизвестен.
    bench = {} if ledger and as_of < date(2026, 9, 30) else None
    leaks = build_report(ops, company_id, as_of, industry, bench=bench, deduplicate=not ledger, balances=balances)
    if bench == {}:
        leaks.warnings.append(
            "Синтетический справочник от30.09.2026 недоступен на выбранную дату; сравнение отключено."
        )
    findings = []
    deferred = 0
    for f in leaks.findings:
        item = {
            "kind": f.kind,
            "nature": f.nature,
            "certainty": f.certainty,
            "title": f.title,
            "amount_minor": f.amount_minor,
            "period": f.period,
            "evidence": list(f.evidence),
            "action": f.action,
            "blocked_by_cash_gap": False,
        }
        if f.kind == "idle_cash" and cash["status"] != "ok":
            # Согласование: впереди нехватка — свободные деньги понадобятся самому бизнесу.
            item["blocked_by_cash_gap"] = True
            item["action"] = (
                "Пока не размещайте: впереди возможная нехватка денег. "
                "Вернитесь к этому, когда прогноз станет спокойным."
            )
            deferred += f.amount_minor
        if f.kind == "overdraft_interest":
            neg = _negative_days(ops, leaks.window_start, as_of, balances)
            if neg:
                item["evidence"].append(f"Это цена прошлых разрывов: {neg} дн. за год остаток был отрицательным")
            if cash["first_gap_date"]:
                item["evidence"].append(
                    f"Следующий возможный разрыв — {cash['first_gap_date']:%d.%m}: подготовьтесь заранее"
                )
        findings.append(item)
    t = leaks.totals
    leaks.warnings.append(
        "Оценки отдельных направлений могут пересекаться: не складывайте их в общий эффект. "
        "Например, смена тарифа эквайринга и переход на СБП — отдельные варианты относительно текущего тарифа."
    )
    return {
        "loss_per_year_minor": t.get("loss_per_year_minor", 0),
        "opportunity_per_year_minor": t.get("opportunity_per_year_minor", 0) - deferred,
        "opportunity_deferred_minor": deferred,
        "one_off_loss_minor": t.get("one_off_loss_window_minor", 0),
        "frozen_minor": t.get("frozen_window_minor", 0),
        "signals": t.get("signals", 0),
        "findings": findings,
        "assumptions": leaks.assumptions,
        "warnings": leaks.warnings,
    }


def _clients_block(rating, stress, cfg):
    if not rating.applicable:
        return {
            "applicable": False,
            "status": "unknown",
            "message": "Недостаточно данных об отдельных B2B-клиентах для оценки зависимости. "
            "Это не подтверждает отсутствие зависимости.",
            "top_client": None,
            "at_risk": [],
            "stress": [],
        }
    by_share = sorted(rating.clients, key=lambda c: -c.revenue_share)
    top = by_share[0]
    at_risk = [
        c for c in rating.clients if (c.grade == "D" or c.early_warning) and c.revenue_share >= cfg.client_min_share
    ]
    fragile = any(s.creates_gap for s in stress.scenarios)
    status: Status = "risk" if fragile else "watch" if at_risk else "ok"
    if fragile:
        message = describe(next(s for s in stress.scenarios if s.creates_gap))
    elif at_risk:
        c = at_risk[0]
        # Причина попадания в список: ранний сигнал ухода важнее общей оценки клиента.
        why = c.early_warning.reasons[0] if c.early_warning else c.grade_label
        message = f"{c.counterparty_name}: {why[0].lower() + why[1:]} — {c.revenue_share:.0%} выручки."
    else:
        message = f"Крупнейший клиент — {top.counterparty_name} ({top.revenue_share:.0%} выручки), платит стабильно."
    return {
        "applicable": True,
        "status": status,
        "message": message,
        "top_client": {
            "name": top.counterparty_name,
            "share": top.revenue_share,
            "grade": top.grade,
            "grade_label": top.grade_label,
        },
        "at_risk": [
            {
                "name": c.counterparty_name,
                "grade": c.grade,
                "grade_label": c.grade_label,
                "share": c.revenue_share,
                "reasons": (c.early_warning.reasons if c.early_warning else []) + c.reasons,
            }
            for c in at_risk
        ],
        "stress": [
            {
                "title": s.title,
                "text": describe(s),
                "kind": s.kind,
                "first_gap_date": s.first_gap_date,
                "creates_gap": s.creates_gap,
                "worst_day_shortfall_minor": s.worst_day_shortfall_minor,
                "basis": s.basis,
            }
            for s in stress.scenarios[:5]
        ],
    }


def _actions(cash, money, clients, cfg) -> list[Action]:
    out: list[Action] = []
    plan = cash["plan"]
    if cash["status"] in ("risk", "watch") and plan:
        for step in plan["steps"]:
            out.append(
                Action(
                    "now" if cash["status"] == "risk" else "this_month",
                    step["title"],
                    cash["message"],
                    step["amount_minor"],
                    "cash",
                )
            )
    for c in clients["at_risk"]:
        out.append(
            Action("now", f"Позвоните {c['name']}", f"{c['grade_label']}; {c['share']:.0%} выручки", 0, "clients")
        )
    fragile = [s for s in clients["stress"] if s["creates_gap"]]
    if fragile and not clients["at_risk"]:
        s = fragile[0]
        out.append(
            Action(
                "now" if cash["status"] == "risk" else "this_month",
                "Снизьте зависимость от одного клиента",
                f"{s['text']} Договоритесь о сроках оплаты и держите резерв на этот случай.",
                s["worst_day_shortfall_minor"],
                "clients",
            )
        )
    for f in money["findings"]:
        if f["nature"] == "frozen" or f["blocked_by_cash_gap"]:
            continue
        urgency: Urgency = (
            "later"
            if f["kind"] in ("idle_cash", "account_fee_above_peers") or f["nature"] == "signal"
            else "this_month"
        )
        if f["nature"] == "signal":
            why = f"+{rub(f['amount_minor'])} за 3 месяца к прошлому году"
        elif f["period"] == "year":
            why = f"{rub(f['amount_minor'])} в год"
        else:
            why = f"{rub(f['amount_minor'])} за последний год"
        out.append(Action(urgency, f["title"], why, f["amount_minor"], "money"))
    # Шаги плана сохраняют свой порядок (сначала бесплатные, потом кредит), прочее — по сумме.
    order = {id(a): i for i, a in enumerate(out)}
    out.sort(
        key=lambda a: (
            _URGENCY_RANK[a.urgency],
            a.source != "cash",
            order[id(a)] if a.source == "cash" else -a.amount_minor,
        )
    )
    return out[: cfg.top_actions]


def build_pulse(
    operations: Sequence[Operation],
    company_id: str,
    as_of: date,
    industry: str | None = None,
    buffer_minor: int | None = None,
    cfg: PulseConfig | None = None,
    *,
    curve: BaseCurve | None = None,
    ledger: bool = False,
    balances: dict[date, int] | None = None,
    cash_available: bool = True,
    cash_reliable: bool = True,
) -> PulseReport:
    cfg = cfg or PulseConfig()
    history = [op for op in operations if op.op_date <= as_of]
    history, dups = (history, 0) if ledger else drop_export_duplicates(history)
    warnings = [f"Убрано строк-дублей выгрузки: {dups} — остаток дня сходится без них."] if dups else []
    rating = rate_counterparties(history, company_id, as_of)
    curve_for_stress = curve if curve is not None else build_base_curve(history, company_id, as_of)
    stress = stress_clients(curve_for_stress, history, rating=rating)
    cash = _cash_block(history, company_id, as_of, buffer_minor, cfg, stress,
                       curve_for_stress, cash_available, cash_reliable)
    cash.pop("_plan")
    money = _money_block(history, company_id, as_of, industry, cash, ledger=ledger, balances=balances)
    clients = _clients_block(rating, stress, cfg)
    losses = money["loss_per_year_minor"] + money["one_off_loss_minor"]
    money["status"] = "unknown" if not history else "watch" if losses >= cfg.money_watch_minor else "ok"

    status = max((cash["status"], clients["status"], money["status"]), key=_STATUS_RANK.__getitem__)
    # Спокойный аудит расходов не подтверждает достаточность данных прогноза.
    # Сигналы watch/risk при этом сохраняют приоритет над неизвестностью.
    if cash["status"] == "unknown" and status == "ok":
        status = "unknown"
    parts = [cash["message"]]
    if money["findings"]:
        parts.append("Найдены статьи расходов и возможности; проверьте отдельные варианты ниже.")
    if clients["applicable"] and clients["status"] != "ok" and clients["message"] not in parts:
        parts.append(clients["message"])
    if not history:
        warnings.append("Нет операций: аудит расходов и зависимости от клиентов недоступен.")
    return PulseReport(
        company_id=company_id,
        as_of=as_of,
        method_version=METHOD_VERSION,
        status=status,
        headline=" ".join(parts),
        cash=cash,
        money=money,
        clients=clients,
        actions=_actions(cash, money, clients, cfg),
        warnings=warnings + cash["warnings"] + money["warnings"] + rating.warnings + stress.warnings,
    )
