# Основа: пользовательский cashcast-advisor; интеграционная версия поддерживается в CashCast.
"""План спасения от кассового разрыва: какие платежи сдвинуть и сколько занять.

Действие плана — сдвиг конкретного потока базовой кривой по времени или кредит, поэтому
планировщику неважно, чья кривая (наша или прогноз бэкенда). Цель — остаток не ниже
подушки на всём горизонте 45 дней. Перенос принимается, только если уменьшает суммарную
«площадь» провала ниже подушки: так он не может тихо создать новую яму позже.

Рычаги от дешёвых к дорогим:
1. перенести вывод денег владельцем и переводы на свой счёт в другом банке (цена 0);
2. отложить оплату поставщикам в пределах того, насколько позже обычного компания уже
   платила (по своей истории);
3. кредит/овердрафт на остаток нехватки (цена — проценты по ставке из настроек).
Налоги, зарплату, кредиты, аренду не трогаем никогда. «Попросить клиента заплатить раньше»
и «вернуть деньги из другого банка» показываем как советы, но в расчёт спасения не включаем:
это не в руках предпринимателя или мы не знаем остаток на чужом счёте.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from typing import Literal

from .baseline_curve import BaseCurve, Flow
from .counterparties import rate_counterparties
from .dataset import Operation
from .documents import parse_document, parse_purpose
from .outflows import classify_outflow

METHOD_VERSION = "rescue-plan-0.1"


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    display_days: int = 30
    buffer_minor: int | None = None  # задаёт пользователь; None — считаем автоматически
    buffer_share_of_weekly_hard: float = 0.5  # подушка = 50% средней недели жёстких платежей
    supplier_max_defer_days: int = 21
    supplier_default_defer_days: int = 14  # если истории оплат поставщикам мало
    supplier_min_lags: int = 10
    credit_rate_annual_bp: int = 2000  # 20% годовых, в базисных пунктах — без float в деньгах
    credit_round_minor: int = 100_000  # кредит округляем вверх до 1000 ₽
    stress_inflow_drop: float = 0.20  # проверка плана при падении поступлений на 20%
    early_payment_suggestions: int = 3
    # False (по умолчанию): предупреждение — по кривой с привычками владельца, план — по
    # кривой без них, а «не выводите деньги» — совет. True — прежнее поведение, когда перенос
    # вывода считался бесплатным рычагом (оставлено для сравнения в backtest).
    owner_habits_as_lever: bool = False


ActionKind = Literal[
    "postpone_owner",
    "postpone_internal",
    "defer_suppliers",
    "credit",
    "request_early_payment",
    "return_from_other_bank",
]


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    title: str
    amount_minor: int
    from_date: date | None
    to_date: date | None
    cost_minor: int
    counted: bool  # входит ли в расчёт «разрыв закрыт»
    min_balance_gain_minor: int  # на сколько поднялся минимум остатка после действия
    details: list[str]


@dataclass(slots=True)
class PlanVariant:
    name: Literal["no_credit", "with_credit"]
    title: str
    resolved: bool
    actions: list[Action]
    total_cost_minor: int
    min_balance_minor: int
    min_balance_date: date
    first_gap_date: date | None
    balances_display_minor: list[int]
    stress_holds: bool  # нет минуса при падении поступлений на stress_inflow_drop
    stress_min_balance_minor: int


@dataclass(slots=True)
class RescuePlan:
    company_id: str
    as_of: date
    method_version: str
    horizon_days: int
    display_days: int
    buffer_minor: int
    buffer_source: Literal["user", "auto"]
    needs_rescue: bool
    # Расходы стабильно выше поступлений: перенос и короткий кредит лишь откладывают яму.
    structural_shortfall: bool
    base: dict[str, object]
    days_display: list[date]
    base_balances_display_minor: list[int]
    variants: list[PlanVariant] = field(default_factory=list)
    suggestions: list[Action] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # «Если выводить деньги как обычно»: та же кривая с привычками владельца (для
    # предупреждения). None — привычек нет или они считаются рычагом плана.
    base_if_owner_withdraws: dict[str, object] | None = None
    base_if_owner_withdraws_display_minor: list[int] | None = None

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rub(minor: int) -> str:
    return f"{minor / 100:,.0f} ₽".replace(",", " ")


def _next_business_day(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _shortfall_area(balances: Sequence[int], buffer: int) -> int:
    return sum(buffer - b for b in balances if b < buffer)


def _curve_stats(curve: BaseCurve, flows: Sequence[Flow], buffer: int) -> dict[str, object]:
    bal = curve.balances(flows)
    days = curve.days
    i_min = min(range(len(bal)), key=bal.__getitem__)
    first_gap = next((d for d, b in zip(days, bal, strict=True) if b < 0), None)
    first_below = next((d for d, b in zip(days, bal, strict=True) if b < buffer), None)
    return {
        "min_balance_minor": bal[i_min],
        "min_balance_date": days[i_min],
        "first_gap_date": first_gap,
        "max_deficit_minor": max(0, -bal[i_min]),
        "first_below_buffer_date": first_below,
    }


def auto_buffer(curve: BaseCurve, share: float) -> int:
    """Подушка: доля средней недели жёстких платежей по календарю горизонта."""
    hard = sum(-f.amount_minor for f in curve.flows if f.flexibility == "hard" and f.amount_minor < 0)
    weekly = hard * 7 / curve.horizon_days
    return int(weekly * share)


def supplier_tolerance_days(operations: Sequence[Operation], as_of: date, cfg: PlannerConfig) -> tuple[int, str]:
    """Насколько позже обычного компания уже платила поставщикам (p90 − медиана задержки)."""
    lags = []
    for op in operations:
        if op.direction != "out" or not (as_of - timedelta(days=365) < op.op_date <= as_of):
            continue
        if classify_outflow(op).kind != "purchases":
            continue
        doc = parse_document(op.purpose)
        if doc and 0 <= (lag := (op.op_date - doc.doc_date).days) <= 365:
            lags.append(lag)
    if len(lags) < cfg.supplier_min_lags:
        return cfg.supplier_default_defer_days, (
            f"истории оплат поставщикам мало — допустимая отсрочка по умолчанию {cfg.supplier_default_defer_days} дн."
        )
    ordered = sorted(lags)
    p90 = ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]
    median = statistics.median(ordered)
    days = int(max(0, min(cfg.supplier_max_defer_days, p90 - median)))
    return days, (f"обычно вы платите поставщикам через {median:g} дн. после документа, а 10% оплат — позже {p90} дн.")


def _move(flows: list[Flow], ref: str, new_day: date) -> list[Flow]:
    return [replace(f, day=new_day) if f.ref == ref else f for f in flows]


def _greedy_moves(
    curve: BaseCurve,
    flows: list[Flow],
    candidates: Sequence[Flow],
    target: Callable[[Flow, date], date | None],
    buffer: int,
) -> tuple[list[Flow], list[tuple[Flow, date]]]:
    """Переносит потоки по одному, пока это уменьшает провал ниже подушки."""
    moved: list[tuple[Flow, date]] = []
    for cand in sorted(candidates, key=lambda f: f.day):
        bal = curve.balances(flows)
        area = _shortfall_area(bal, buffer)
        if area == 0:
            break
        bad = [d for d, b in zip(curve.days, bal, strict=True) if b < buffer]
        if cand.day > bad[-1]:
            continue  # поток после ямы — переносить незачем
        new_day = target(cand, bad[-1])
        if new_day is None or new_day <= cand.day or new_day > curve.days[-1]:
            continue
        trial = _move(flows, cand.ref, new_day)
        if _shortfall_area(curve.balances(trial), buffer) < area:
            flows = trial
            moved.append((cand, new_day))
    return flows, moved


def _min(curve: BaseCurve, flows: Sequence[Flow]) -> int:
    return min(curve.balances(flows))


def plan_rescue(
    curve: BaseCurve,
    operations: Sequence[Operation],
    cfg: PlannerConfig | None = None,
) -> RescuePlan:
    cfg = cfg or PlannerConfig()
    as_of = curve.as_of
    history = [op for op in operations if op.op_date <= as_of]
    if cfg.buffer_minor is not None:
        buffer, buffer_source = cfg.buffer_minor, "user"
    else:
        buffer, buffer_source = auto_buffer(curve, cfg.buffer_share_of_weekly_hard), "auto"
    full_flows = list(curve.flows)
    habit_flows = [f for f in full_flows if f.source == "owner_habit"]
    base_flows = full_flows if cfg.owner_habits_as_lever else [f for f in full_flows if f.source != "owner_habit"]
    display = min(cfg.display_days, curve.horizon_days)
    plan = RescuePlan(
        company_id=curve.company_id,
        as_of=as_of,
        method_version=METHOD_VERSION,
        horizon_days=curve.horizon_days,
        display_days=display,
        buffer_minor=buffer,
        buffer_source=buffer_source,
        needs_rescue=False,
        structural_shortfall=False,
        base=_curve_stats(curve, base_flows, buffer),
        days_display=curve.days[:display],
        base_balances_display_minor=curve.balances(base_flows)[:display],
        assumptions=list(curve.assumptions),
        warnings=list(curve.warnings),
    )
    plan.assumptions.append(
        f"Подушка {_rub(buffer)} — "
        + ("задана пользователем." if buffer_source == "user" else "50% средней недели обязательных платежей.")
    )
    if curve.warnings and not curve.flows:
        return plan
    if habit_flows and not cfg.owner_habits_as_lever:
        plan.base_if_owner_withdraws = _curve_stats(curve, full_flows, buffer)
        plan.base_if_owner_withdraws_display_minor = curve.balances(full_flows)[:display]
        plan.assumptions.append(
            "План считается без вывода денег владельцем: в трудные месяцы владельцы обычно откладывают его сами."
        )
        plan.suggestions += _owner_advice(curve, full_flows, habit_flows, buffer)
    if _shortfall_area(curve.balances(base_flows), buffer) == 0:
        plan.suggestions += _suggestions(history, as_of, cfg) if plan.suggestions else []
        return plan
    plan.needs_rescue = True
    plan.structural_shortfall = _is_structural(curve, base_flows, buffer)
    if plan.structural_shortfall:
        net = sum(f.amount_minor for f in base_flows)
        plan.warnings.append(
            f"Похоже на структурную нехватку: за {curve.horizon_days} дн. расходы превышают "
            f"поступления на {_rub(-net)}, и остаток снижается до конца горизонта. Перенос "
            "платежей и короткий кредит лишь отодвигают проблему — нужны изменения в доходах "
            "или расходах."
        )

    horizon_end = curve.days[-1]
    flows = list(base_flows)
    actions: list[Action] = []

    # 1. Деньги владельца и переводы на свой счёт: перенести на день после ямы.
    for flex, kind, verb in (
        ("owner", "postpone_owner", "Отложите вывод денег владельцем"),
        ("internal", "postpone_internal", "Отложите перевод на свой счёт в другом банке"),
    ):
        before = _min(curve, flows)
        cands = [f for f in flows if f.flexibility == flex]
        flows, moved = _greedy_moves(curve, flows, cands, lambda f, last_bad: _next_business_day(last_bad), buffer)
        for f, new_day in moved:
            after_text = f"на {new_day:%d.%m}" if new_day <= horizon_end else f"на после {horizon_end:%d.%m}"
            actions.append(
                Action(
                    kind=kind,
                    title=f"{verb} {_rub(-f.amount_minor)} (обычно около {f.day:%d.%m}) — {after_text}",
                    amount_minor=-f.amount_minor,
                    from_date=f.day,
                    to_date=new_day,
                    cost_minor=0,
                    counted=True,
                    min_balance_gain_minor=0,
                    details=[
                        "Обычно вы выводите примерно столько каждый месяц; перенос бесплатный и зависит только от вас."
                    ],
                )
            )
        if moved:
            gain = _min(curve, flows) - before
            for i in range(len(actions) - len(moved), len(actions)):
                actions[i] = replace(actions[i], min_balance_gain_minor=gain // len(moved))

    # 2. Поставщики: сдвиг в пределах исторической «терпимости».
    tol_days, tol_note = supplier_tolerance_days(history, as_of, cfg)
    if tol_days > 0:
        before = _min(curve, flows)

        def supplier_target(f: Flow, last_bad: date) -> date | None:
            return min(f.day + timedelta(days=tol_days), _next_business_day(last_bad))

        cands = [f for f in flows if f.flexibility == "flexible"]
        flows, moved = _greedy_moves(curve, flows, cands, supplier_target, buffer)
        if moved:
            total = sum(-f.amount_minor for f, _ in moved)
            first = min(f.day for f, _ in moved)
            last = max(f.day for f, _ in moved)
            shift = max((nd - f.day).days for f, nd in moved)
            actions.append(
                Action(
                    kind="defer_suppliers",
                    title=(
                        f"Платите поставщикам до {shift} дн. позже обычного "
                        f"с {first:%d.%m} по {last:%d.%m} (платежи на {_rub(total)})"
                    ),
                    amount_minor=total,
                    from_date=first,
                    to_date=max(nd for _, nd in moved),
                    cost_minor=0,
                    counted=True,
                    min_balance_gain_minor=_min(curve, flows) - before,
                    details=[
                        tol_note[0].upper() + tol_note[1:].rstrip(".") + ".",
                        "Договоритесь с поставщиками заранее: отсрочка без предупреждения портит отношения.",
                    ],
                )
            )

    no_credit_flows = flows
    resolved = _shortfall_area(curve.balances(no_credit_flows), buffer) == 0
    plan.variants.append(
        _variant(curve, base_flows, no_credit_flows, actions, buffer, cfg, "no_credit", resolved, display)
    )

    # 3. Кредит на остаток нехватки.
    if not resolved:
        credit_action, credit_flows = _credit(curve, no_credit_flows, buffer, cfg)
        plan.variants.append(
            _variant(
                curve,
                base_flows,
                credit_flows,
                [*actions, credit_action],
                buffer,
                cfg,
                "with_credit",
                _shortfall_area(curve.balances(credit_flows), buffer) == 0,
                display,
            )
        )

    plan.suggestions += _suggestions(history, as_of, cfg)
    return plan


def _owner_advice(curve: BaseCurve, full_flows: list[Flow], habit_flows: list[Flow], buffer: int) -> list[Action]:
    """Совет «не выводите деньги до …», если обычный вывод роняет остаток ниже подушки."""
    bal = curve.balances(full_flows)
    bad = [d for d, b in zip(curve.days, bal, strict=True) if b < buffer]
    if not bad:
        return []
    until = _next_business_day(bad[-1])
    out = []
    for flex, kind, what in (
        ("owner", "postpone_owner", "выводите деньги из бизнеса"),
        ("internal", "postpone_internal", "переводите деньги на свой счёт в другом банке"),
    ):
        planned = [f for f in habit_flows if f.flexibility == flex and f.day < until]
        if not planned:
            continue
        amount = sum(-f.amount_minor for f in planned)
        out.append(
            Action(
                kind=kind,  # type: ignore[arg-type]
                title=f"Не {what} до {until:%d.%m}",
                amount_minor=amount,
                from_date=planned[0].day,
                to_date=until,
                cost_minor=0,
                counted=False,
                min_balance_gain_minor=0,
                details=[
                    f"Если сделать это как обычно (около {_rub(amount)}), остаток опустится "
                    f"ниже подушки {bad[0]:%d.%m}.",
                    "План ниже уже считает, что вы этого не делаете.",
                ],
            )
        )
    return out


def _is_structural(curve: BaseCurve, flows: Sequence[Flow], buffer: int) -> bool:
    """Минимум в последние 5 дней горизонта и чистый поток за горизонт хуже минус подушки."""
    bal = curve.balances(flows)
    i_min = min(range(len(bal)), key=bal.__getitem__)
    net = sum(f.amount_minor for f in flows)
    return i_min >= len(bal) - 5 and net < -max(buffer, 1)


def _credit(curve: BaseCurve, flows: list[Flow], buffer: int, cfg: PlannerConfig) -> tuple[Action, list[Flow]]:
    bal = curve.balances(flows)
    days = curve.days
    need = max(buffer - b for b in bal)
    amount = -(-need // cfg.credit_round_minor) * cfg.credit_round_minor  # вверх до 1000 ₽
    bad = [d for d, b in zip(days, bal, strict=True) if b < buffer]
    draw = bad[0]
    # Гасим только с процентами: стоимость нельзя показать отдельно и забыть на графике.
    repay: date | None = None
    candidate = _next_business_day(bad[-1])
    while candidate <= days[-1]:
        interest = (amount * cfg.credit_rate_annual_bp * max(1, (candidate - draw).days) + 10_000 * 365 - 1) // (
            10_000 * 365
        )
        trial = [
            *flows,
            Flow("credit:draw", draw, amount, "credit", "credit", "Кредит", "plan"),
            Flow("credit:repay", candidate, -amount - interest, "credit", "credit", "Погашение кредита", "plan"),
        ]
        if min(curve.balances(trial)) >= buffer:
            repay = candidate
            break
        candidate = _next_business_day(candidate)
    end = repay or days[-1]
    term = max(1, (end - draw).days)
    cost = (amount * cfg.credit_rate_annual_bp * term + 10_000 * 365 - 1) // (10_000 * 365)
    # Если срок выходит за горизонт, учитываем накопленные проценты резервом на его конце.
    # Основной долг при этом остаётся, что явно написано в деталях сценария.
    new_flows = [
        *flows,
        Flow("credit:draw", draw, amount, "credit", "credit", "Кредит", "plan"),
        Flow("credit:cost", end, -cost, "credit", "credit", "Проценты", "plan"),
    ]
    if repay is not None:
        new_flows.append(Flow("credit:repay", repay, -amount, "credit", "credit", "Погашение кредита", "plan"))
    details = [
        f"Ставка {cfg.credit_rate_annual_bp / 100:g}% годовых — настройка, уточните условия в банке.",
        f"Стоимость за {term} дн.: {_rub(cost)}.",
    ]
    if repay is None:
        details.append(
            f"На {days[-1]:%d.%m} основной долг {_rub(amount)} остаётся непогашенным; "
            "проценты после горизонта неизвестны. Нужен более длинный срок."
        )
    title = f"Рассмотрите финансирование {_rub(amount)} с {draw:%d.%m}" + (
        f" до {repay:%d.%m}" if repay else f" на срок дольше {term} дн."
    )
    action = Action(
        kind="credit",
        title=title,
        amount_minor=amount,
        from_date=draw,
        to_date=repay,
        cost_minor=cost,
        counted=True,
        min_balance_gain_minor=min(curve.balances(new_flows)) - min(bal),
        details=details,
    )
    return action, new_flows


def _variant(
    curve: BaseCurve,
    base_flows: list[Flow],
    flows: list[Flow],
    actions: list[Action],
    buffer: int,
    cfg: PlannerConfig,
    name: Literal["no_credit", "with_credit"],
    resolved: bool,
    display: int,
) -> PlanVariant:
    stats = _curve_stats(curve, flows, buffer)
    stress_min = min(curve.balances(_stressed(base_flows, flows, cfg.stress_inflow_drop)))
    if name == "no_credit":
        title = "Без кредита" if resolved else "Без кредита (разрыв закрывается не полностью)"
    else:
        title = "С кредитом"
    return PlanVariant(
        name=name,
        title=title,
        resolved=resolved,
        actions=list(actions),
        total_cost_minor=sum(a.cost_minor for a in actions),
        min_balance_minor=stats["min_balance_minor"],  # type: ignore[arg-type]
        min_balance_date=stats["min_balance_date"],  # type: ignore[arg-type]
        first_gap_date=stats["first_gap_date"],  # type: ignore[arg-type]
        balances_display_minor=curve.balances(flows)[:display],
        stress_holds=stress_min >= 0,
        stress_min_balance_minor=stress_min,
    )


def _stressed(base_flows: list[Flow], flows: list[Flow], drop: float) -> list[Flow]:
    """Те же действия плана, но поступления ниже на drop (сценарий кейса «спад выручки»)."""
    del base_flows  # поступления не двигаются планом, достаточно уменьшить их в итоговом наборе
    return [
        replace(f, amount_minor=round(f.amount_minor * (1 - drop))) if f.flexibility == "inflow" else f for f in flows
    ]


def _suggestions(history: Sequence[Operation], as_of: date, cfg: PlannerConfig) -> list[Action]:
    out: list[Action] = []
    rating = rate_counterparties(history, history[0].company_id if history else "", as_of)
    reliable = [c for c in rating.clients if c.grade in ("A", "B") and c.early_warning is None]
    reliable.sort(key=lambda c: -c.received_minor)
    for c in reliable[: cfg.early_payment_suggestions]:
        out.append(
            Action(
                kind="request_early_payment",
                title=f"Попросите {c.counterparty_name} оплатить раньше",
                amount_minor=0,
                from_date=None,
                to_date=None,
                cost_minor=0,
                counted=False,
                min_balance_gain_minor=0,
                details=[
                    c.reasons[0],
                    f"Надёжный клиент: {c.revenue_share:.0%} поступлений за год. "
                    "Эффект не учтён в плане — решение за клиентом.",
                ],
            )
        )

    year_ago = as_of - timedelta(days=365)
    sent = returned = 0
    for op in history:
        if op.op_date <= year_ago:
            continue
        if op.direction == "out" and classify_outflow(op).flexibility == "internal":
            sent += op.amount_minor
        elif op.direction == "in" and parse_purpose(op.purpose).non_operating == "own_transfer":
            returned += op.amount_minor
    if sent > returned:
        out.append(
            Action(
                kind="return_from_other_bank",
                title="Проверьте свой счёт в другом банке",
                amount_minor=sent - returned,
                from_date=None,
                to_date=None,
                cost_minor=0,
                counted=False,
                min_balance_gain_minor=0,
                details=[
                    f"За год вы перевели туда на {_rub(sent - returned)} больше, чем вернули. "
                    "Если деньги там остались, их можно вернуть; остаток того счёта нам "
                    "не виден, поэтому в плане это не учтено."
                ],
            )
        )
    return out
