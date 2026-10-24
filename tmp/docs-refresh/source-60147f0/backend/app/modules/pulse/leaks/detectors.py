# Основа: пользовательский cashcast-leaks; интеграционная версия поддерживается в CashCast.
"""Детекторы утечек. Каждый — маленькая функция Context -> list[Finding].

«Факт» — посчитано по выписке (и справочнику похожих бизнесов). «Оценка» — зависит от
допущения из LeakConfig, и это видно в evidence. Годовые суммы считаются по последним
window_days; если истории меньше, факт пересчитывается на год с пометкой.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..advisor.dataset import Operation
from ..advisor.outflows import classify_outflow
from .benchmarks import PeerStats
from .model import Finding, LeakConfig, pct, rub
from .money import parse_commission

_MONTHS = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]
_OVERDRAFT_RE = re.compile(
    r"процент\w*\s+за\s+пользование\s+овердрафт"
    r"|процент\w*\s+по\s+договору\s+кредитной\s+линии",
    re.IGNORECASE,
)
_ENFORCEMENT_RE = re.compile(r"исполнительн\w+\s+лист", re.IGNORECASE)
_TAX_COLLECTION_RE = re.compile(r"поручени\w+\s+налогового\s+органа", re.IGNORECASE)
_WRONG_REQ_RE = re.compile(r"неверно\s+указаны\s+реквизиты|возврат\s+ошибочн", re.IGNORECASE)
_ACCOUNT_FEE_RE = re.compile(r"ведени\w+\s+сч[её]та", re.IGNORECASE)
_CREEP_KINDS = {
    "rent": "Аренда",
    "utilities": "Коммунальные услуги и связь",
    "services": "Услуги",
    "fees": "Комиссии банка",
}


@dataclass(frozen=True, slots=True)
class Context:
    as_of: date
    window_start: date  # окно (window_start, as_of]
    ops: Sequence[Operation]  # вся история до as_of включительно
    window_ops: Sequence[Operation]
    annual_factor: float  # 365 / покрытые дни окна (1.0 при полном годе)
    peers: PeerStats | None
    cfg: LeakConfig
    balances: dict[date, int] | None = None


def _key(op: Operation) -> str:
    return op.counterparty_inn or (op.counterparty_name or "").strip().lower() or "?"


def channel_totals(ops: Sequence[Operation]) -> dict[str, tuple[int, int]]:
    """{'card'|'sbp': (оборот, комиссия)} по зачислениям за окно."""
    gross: dict[str, int] = defaultdict(int)
    fee: dict[str, int] = defaultdict(int)
    for op in ops:
        if op.direction != "in":
            continue
        c = parse_commission(op.purpose)
        if c:
            gross[c.channel] += c.gross_minor
            fee[c.channel] += c.fee_minor
    return {ch: (gross[ch], fee[ch]) for ch in gross}


def card_rate_above_peers(ctx: Context) -> list[Finding]:
    totals = channel_totals(ctx.window_ops)
    if "card" not in totals or ctx.peers is None or ctx.peers.card_rate is None:
        return []
    gross, fee = totals["card"]
    rate = fee / gross
    peer = ctx.peers.card_rate
    if rate - peer <= ctx.cfg.rate_tolerance:
        return []
    overpay = round((rate - peer) * gross * ctx.annual_factor)
    return [
        Finding(
            kind="card_rate_above_peers",
            nature="loss",
            certainty="fact",
            title="Вы переплачиваете за эквайринг",
            amount_minor=overpay,
            period="year",
            evidence=[
                f"Ваша комиссия за оплату картой — {pct(rate)} от оборота",
                f"У похожих бизнесов ({ctx.peers.scope}) — {pct(peer)}",
                f"Оборот по картам за год — {rub(round(gross * ctx.annual_factor))}",
            ],
            action="Попросите банк пересмотреть тариф эквайринга: с вашими оборотами ставка "
            f"около {pct(peer)} — обычная практика.",
            details={"own_rate": round(rate, 5), "peer_rate": round(peer, 5), "card_gross_minor": gross},
        )
    ]


def sbp_shift(ctx: Context) -> list[Finding]:
    totals = channel_totals(ctx.window_ops)
    if "card" not in totals:
        return []
    card_gross, card_fee = totals["card"]
    card_rate = card_fee / card_gross
    if "sbp" in totals:
        sbp_rate, source = totals["sbp"][1] / totals["sbp"][0], "ваша ставка СБП"
    elif ctx.peers and ctx.peers.sbp_rate is not None:
        sbp_rate, source = ctx.peers.sbp_rate, f"СБП у похожих бизнесов ({ctx.peers.scope})"
    else:
        return []
    if card_rate - sbp_rate <= ctx.cfg.rate_tolerance:
        return []
    share = ctx.cfg.sbp_shift_share
    saving = round((card_rate - sbp_rate) * card_gross * ctx.annual_factor * share)
    return [
        Finding(
            kind="sbp_shift",
            nature="opportunity",
            certainty="estimate",
            title="Принимайте часть оплат по QR-коду (СБП)",
            amount_minor=saving,
            period="year",
            evidence=[
                f"Оплата картой стоит вам {pct(card_rate)}, по СБП — {pct(sbp_rate)} ({source})",
                f"Допущение: по QR будут платить {share:.0%} покупателей, которые сейчас платят картой",
            ],
            action="Поставьте QR-код СБП на кассе и в счетах; предложите его первым способом оплаты.",
            details={"card_rate": round(card_rate, 5), "sbp_rate": round(sbp_rate, 5), "shift_share": share},
        )
    ]


def idle_cash(ctx: Context) -> list[Finding]:
    # Остаток конца дня — по последней операции дня (он одинаков у всех операций дня).
    daily: dict[date, int] = {}
    for op in ctx.window_ops:
        if op.balance_eod_minor is not None:
            daily[op.op_date] = op.balance_eod_minor
    if ctx.balances is not None:
        # Подтверждённый EOD не зависит от наличия операции в тот же день.
        daily = {d: v for d, v in ctx.balances.items() if ctx.window_start < d <= ctx.as_of}
    months = {(d.year, d.month) for d in daily}
    if len(months) < ctx.cfg.idle_min_months:
        return []
    low_day = min(daily, key=daily.__getitem__)
    floor = daily[low_day]
    if floor < ctx.cfg.idle_min_minor:
        return []
    rate = ctx.cfg.deposit_rate_annual
    # Советуем разместить только часть: проверка на датасете показала, что весь прошлогодний
    # минимум на следующий год оставался нетронутым лишь у 44% компаний, половина — у 74%.
    share = ctx.cfg.idle_safe_share
    place = round(floor * share)
    return [
        Finding(
            kind="idle_cash",
            nature="opportunity",
            certainty="estimate",
            title="Деньги лежат без дохода",
            amount_minor=round(place * rate),
            period="year",
            evidence=[
                f"В известных остатках за {len(months)} мес. минимум составил "
                f"{rub(floor)} (минимум — {low_day:%d.%m.%Y})",
                f"Предлагаем разместить {share:.0%} этой суммы — {rub(place)}; остальное — "
                "запас, если в следующем году остаток опустится ниже",
                f"Допущение: ставка {rate:.0%} годовых — уточните условия в банке",
            ],
            action=f"Разместите {rub(place)} на депозит или подключите процент на остаток счёта: "
            "сначала проверьте доступность снятия и будущие обязательства; отсутствие риска не гарантируется.",
            details={
                "floor_minor": floor,
                "floor_date": low_day.isoformat(),
                "recommended_minor": place,
                "safe_share": share,
                "months": len(months),
                "rate": rate,
            },
        )
    ]


def _full_months_before(as_of: date, count: int) -> list[tuple[int, int]]:
    y, m = as_of.year, as_of.month
    out = []
    for _ in range(count):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append((y, m))
    return sorted(out)


def price_creep(ctx: Context) -> list[Finding]:
    """Регулярный платёж тому же получателю: 3 последних полных месяца против тех же
    месяцев год назад. Сравнение «месяц к месяцу» не путает рост цены с сезонностью."""
    now_months = _full_months_before(ctx.as_of, 3)
    ago_months = [(y - 1, m) for y, m in now_months]
    wanted = set(now_months) | set(ago_months)
    sums: dict[tuple[str, str], dict[tuple[int, int], int]] = defaultdict(lambda: defaultdict(int))
    names: dict[tuple[str, str], str | None] = {}
    for op in ctx.ops:
        ym = (op.op_date.year, op.op_date.month)
        if op.direction != "out" or ym not in wanted:
            continue
        kind = classify_outflow(op).kind
        if kind not in _CREEP_KINDS:
            continue
        key = (kind, _key(op))
        sums[key][ym] += op.amount_minor
        names[key] = op.counterparty_name
    out: list[Finding] = []
    for (kind, _), per_month in sums.items():
        if not all(per_month.get(ym) for ym in wanted):
            continue  # нужен платёж в каждом из 6 месяцев — иначе это не регулярный счёт
        now = sum(per_month[ym] for ym in now_months)
        ago = sum(per_month[ym] for ym in ago_months)
        growth = now / ago - 1
        if growth < ctx.cfg.price_growth_threshold:
            continue
        label = f"{_MONTHS[now_months[0][1] - 1]}–{_MONTHS[now_months[-1][1] - 1]}"
        name = names[(kind, _)] or "получатель"
        # Сигнал, а не годовая потеря: проверка на датасете показала, что такой рост
        # удерживается в следующие 3 месяца лишь в ~41% случаев — часто это объём, не цена.
        out.append(
            Finding(
                kind="price_creep",
                nature="signal",
                certainty="fact",
                title=f"{_CREEP_KINDS[kind]}: {name} — расходы +{growth:.1%} к прошлому году",
                amount_minor=now - ago,
                period="window",
                evidence=[
                    f"{label} {now_months[-1][0]}: {rub(now)}",
                    f"{label} {ago_months[-1][0]}: {rub(ago)}",
                    f"Рост {growth:.1%} — выше обычной индексации ({ctx.cfg.price_growth_threshold:.0%})",
                    "Такой рост часто оказывается разовым или связан с объёмом услуг, а не с ценой",
                ],
                action="Проверьте, что выросло — цена или объём. Если цена — запросите обоснование "
                "и сравните предложения других поставщиков.",
                details={"kind": kind, "now_minor": now, "year_ago_minor": ago, "growth": round(growth, 4)},
            )
        )
    return out


def possible_duplicates(ctx: Context) -> list[Finding]:
    groups: dict[tuple, list[Operation]] = defaultdict(list)
    for op in ctx.window_ops:
        if op.direction == "out":
            groups[(op.op_date, _key(op), op.amount_minor, op.purpose)].append(op)
    refunds = [op for op in ctx.ops if op.direction == "in"]
    cases = []
    for (day, who, amount, _), ops in groups.items():
        if len(ops) < 2:
            continue
        returned = any(
            _key(r) == who
            and r.amount_minor == amount
            and day <= r.op_date <= day + timedelta(days=ctx.cfg.duplicate_refund_days)
            for r in refunds
        )
        if not returned:
            cases.append((day, ops[0].counterparty_name, amount, len(ops) - 1))
    if not cases:
        return []
    extra = sum(amount * n for _, _, amount, n in cases)
    return [
        Finding(
            kind="possible_duplicates",
            nature="loss",
            certainty="fact",
            title=f"Возможные двойные платежи: {len(cases)}",
            amount_minor=extra,
            period="window",
            evidence=[
                f"{day:%d.%m.%Y}: {name or 'получатель'} — {rub(amount)} × {n + 1}"
                for day, name, amount, n in cases[:5]
            ]
            + [
                "Одинаковые дата, получатель, сумма и назначение; возврата в течение "
                f"{ctx.cfg.duplicate_refund_days} дней не было",
                "Остаток дня подтверждает, что ушли обе оплаты (это не повтор строки в выписке)",
            ],
            action="Сверьтесь с получателем: если платёж задвоен, запросите возврат или зачёт.",
            details={
                "cases": [
                    {"date": d.isoformat(), "counterparty": n, "amount_minor": a, "extra_copies": k}
                    for d, n, a, k in cases
                ]
            },
        )
    ]


def overdraft_interest(ctx: Context) -> list[Finding]:
    ops = [op for op in ctx.window_ops if op.direction == "out" and op.purpose and _OVERDRAFT_RE.search(op.purpose)]
    if not ops:
        return []
    total = sum(op.amount_minor for op in ops)
    return [
        Finding(
            kind="overdraft_interest",
            nature="loss",
            certainty="fact",
            title="Проценты за овердрафт и кредитную линию",
            amount_minor=round(total * ctx.annual_factor),
            period="year",
            evidence=[f"За период: {len(ops)} списаний процентов на {rub(total)}"],
            action="Овердрафт закрывает разрывы, но дорого. Планируйте крупные платежи по прогнозу "
            "остатка и сравните ставку с кредитной линией.",
            details={"payments": len(ops), "window_total_minor": total},
        )
    ]


def forced_collections(ctx: Context) -> list[Finding]:
    ops = [
        op
        for op in ctx.window_ops
        if op.direction == "out"
        and op.purpose
        and (_ENFORCEMENT_RE.search(op.purpose) or _TAX_COLLECTION_RE.search(op.purpose))
    ]
    if not ops:
        return []
    total = sum(op.amount_minor for op in ops)
    court = sum(1 for op in ops if _ENFORCEMENT_RE.search(op.purpose or ""))
    return [
        Finding(
            kind="forced_collections",
            nature="loss",
            certainty="fact",
            title="Деньги списаны принудительно",
            amount_minor=total,
            period="window",
            evidence=[
                f"{court} — по исполнительному листу, {len(ops) - court} — по требованию налоговой; всего {rub(total)}",
                "Принудительное списание обычно означает долг, дошедший до суда или "
                "взыскания, — с пенями, госпошлиной и арестом счёта",
            ],
            action="Отвечайте на претензии и требования ФНС до суда; при нехватке денег "
            "договаривайтесь о рассрочке заранее.",
            details={"court": court, "tax": len(ops) - court},
        )
    ]


def wrong_requisites(ctx: Context) -> list[Finding]:
    returns = [op for op in ctx.window_ops if op.direction == "in" and op.purpose and _WRONG_REQ_RE.search(op.purpose)]
    if not returns:
        return []
    outgoing = [op for op in ctx.ops if op.direction == "out"]
    days = []
    for r in returns:
        # Исходный платёж — строго до возврата: в день возврата обычно уходит повторная оплата.
        orig = [
            o
            for o in outgoing
            if o.amount_minor == r.amount_minor and r.op_date - timedelta(days=30) <= o.op_date < r.op_date
        ]
        if orig:
            days.append((r.op_date - max(o.op_date for o in orig)).days)
    total = sum(r.amount_minor for r in returns)
    avg = sum(days) / len(days) if days else None
    evidence = [f"{len(returns)} платежей вернулись из-за ошибки в реквизитах на {rub(total)}"]
    if avg is not None:
        evidence.append(
            f"Деньги возвращались в среднем через {avg:.0f} дн. — всё это время поставщик не получал оплату"
        )
    return [
        Finding(
            kind="wrong_requisites",
            nature="frozen",
            certainty="fact",
            title="Платежи с ошибкой в реквизитах",
            amount_minor=total,
            period="window",
            evidence=evidence,
            action="Храните реквизиты поставщиков в шаблонах и сверяйте их по счёту перед оплатой.",
            details={"returns": len(returns), "avg_days_frozen": round(avg, 1) if avg else None},
        )
    ]


def account_fee_above_peers(ctx: Context) -> list[Finding]:
    if ctx.peers is None or ctx.peers.account_fee_monthly_minor is None:
        return []
    per_month: dict[tuple[int, int], int] = defaultdict(int)
    for op in ctx.window_ops:
        if op.direction == "out" and op.purpose and _ACCOUNT_FEE_RE.search(op.purpose):
            per_month[(op.op_date.year, op.op_date.month)] += op.amount_minor
    if len(per_month) < 3:
        return []
    own = sorted(per_month.values())[len(per_month) // 2]  # медиана: разовая доплата не в счёт
    peer = ctx.peers.account_fee_monthly_minor
    if own <= peer * 1.10:
        return []
    return [
        Finding(
            kind="account_fee_above_peers",
            nature="loss",
            certainty="fact",
            title="Обслуживание счёта дороже, чем у похожих бизнесов",
            amount_minor=(own - peer) * 12,
            period="year",
            evidence=[f"Вы платите {rub(own)} в месяц, у похожих бизнесов ({ctx.peers.scope}) — {rub(peer)}"],
            action="Проверьте тарифы банка для вашего оборота: возможно, подойдёт пакет дешевле.",
            details={"own_monthly_minor": own, "peer_monthly_minor": peer},
        )
    ]


DETECTORS: tuple[Callable[[Context], list[Finding]], ...] = (
    idle_cash,
    card_rate_above_peers,
    sbp_shift,
    price_creep,
    overdraft_interest,
    forced_collections,
    possible_duplicates,
    account_fee_above_peers,
    wrong_requisites,
)
