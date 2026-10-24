"""Классификация списаний на формулировках из датасета (номера и суммы выдуманы)."""

from datetime import date

import pytest

from app.modules.pulse.advisor.dataset import Operation
from app.modules.pulse.advisor.outflows import KINDS, classify_outflow, classify_text, summarize_outflows


@pytest.mark.parametrize(
    ("purpose", "kind", "flexibility"),
    [
        # Жёсткие: переносить нельзя.
        ("Единый налоговый платеж", "tax", "hard"),
        ("Единый налоговый платёж. НДС не облагается", "tax", "hard"),
        ("ЕНП", "tax", "hard"),
        ("Списание по поручению налогового органа № 5 от 01.02.2025. Взыскание задолженности", "tax", "hard"),
        ("Перечисление заработной платы (аванс) за май 2025 г. по реестру № 3 от 20.05.2025", "payroll", "hard"),
        ("Аванс по заработной плате за май 2025 г. Перечисление на счет сотрудника", "payroll", "hard"),
        ("Оплата услуг по договору ГПХ, чек № 77. НДС не облагается", "payroll", "hard"),
        ("Погашение кредита по договору № КД-1 от 01.01.2025: основной долг 10.00, проценты 1.00", "loan", "hard"),
        ("Лизинговый платеж № 4 по договору лизинга № ЛД-2 от 01.03.2024. В т.ч. НДС 20%", "loan", "hard"),
        ("Уплата процентов за пользование овердрафтом за май 2025 г", "loan", "hard"),
        ("Оплата аренды нежилого помещения по договору № 1/2 за май 2025 г. Без НДС", "rent", "hard"),
        # Аренда POS-терминала — банковская плата, а не аренда помещения.
        ("Плата за аренду POS-терминалов за май 2025 г", "fees", "hard"),
        ("Комиссия за ведение счета за май 2025 г. Без НДС", "fees", "hard"),
        ("Оплата за электроэнергию по договору № 5 за май 2025 г", "utilities", "hard"),
        ("Оплата по счету № 9 от 01.05.2025 за вывоз ТКО", "utilities", "hard"),
        ("Оплата услуг связи и доступа в Интернет по лицевому счету 1 за май 2025 г", "utilities", "hard"),
        ("Списание по исполнительному листу ФС № 1 от 01.01.2025 по делу № А1-2/2025", "enforcement", "hard"),
        # Регулярные расходы бизнеса.
        ("Пополнение рекламного кабинета по договору-оферте. В т.ч. НДС 20%", "marketing", "regular"),
        ("Оплата по счету № 3 от 01.05.2025 за бухгалтерские услуги", "services", "regular"),
        ("Оплата по счету № 3 за предоставление права использования ПО (подписка) за май", "services", "regular"),
        ("Оплата по УПД № 8 от 01.05.2025 за услуги уборки по договору поставки", "services", "regular"),
        ("Оплата по счету № 4 за ремонт автомобиля", "services", "regular"),
        ("Пополнение лицевого счета по договору № 1 (топливные карты). В т.ч. НДС", "fuel_transport", "regular"),
        # Поставщики и разовые покупки — можно двигать.
        ("Оплата по УПД № 12 от 01.05.2025 за молочную продукцию по договору поставки", "purchases", "flexible"),
        ("Оплата по счету № 1 от 01.05.2025 за товар", "purchases", "flexible"),
        ("Оплата по договору субподряда за выполненные работы по акту № 2 от 01.05.2025", "purchases", "flexible"),
        ("Оплата транспортно-экспедиционных услуг по счету № 5", "purchases", "flexible"),
        ("Оплата по счету № 1 от 01.05.2025 за оборудование", "capex", "flexible"),
        ("Предоплата 30% по договору купли-продажи № 1/2 за автомобиль", "capex", "flexible"),
        ("Аванс по договору подряда № 1/2 на ремонт помещения", "capex", "flexible"),
        # Деньги владельца — отложить бесплатно.
        (
            "Выплата дивидендов за 2 квартал 2025 г. согласно решению участника. НДФЛ удержан",
            "owner_withdrawal",
            "owner",
        ),
        ("Перевод собственных средств на личную карту. НДС не облагается", "owner_withdrawal", "owner"),
        ("Перевод на личный счет предпринимателя. НДС не облагается", "owner_withdrawal", "owner"),
        ("Перевод собственных средств ИП на счет физического лица", "owner_withdrawal", "owner"),
        ("Возврат беспроцентного займа учредителю по договору № 1/2", "owner_withdrawal", "owner"),
        # Свой счёт в другом банке — деньги не тратятся.
        (
            "Перевод собственных средств на расчетный счет в АО «Банк-1». НДС не облагается",
            "internal_transfer",
            "internal",
        ),
        (
            "Перечисление остатка денежных средств в связи с закрытием счета на счет в АО «Банк-2»",
            "internal_transfer",
            "internal",
        ),
        ("Что-то совершенно непонятное", "other", "unknown"),
    ],
)
def test_classify_by_purpose(purpose, kind, flexibility):
    cls = classify_text(purpose, "ООО «Кто-то»")
    assert (cls.kind, cls.flexibility) == (kind, flexibility)
    assert cls.matched_by == ("none" if kind == "other" else "purpose")


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Казначейство России (ФНС России)", "tax"),
        ("ПАО «Банк»", "fees"),
        ("Сотрудник 12", "payroll"),
        ("Физическое лицо (самозанятый) 3", "payroll"),
        ("ПАО «Энергосбыт-1»", "utilities"),
        ("Учредитель (физическое лицо)", "owner_withdrawal"),
        ("ООО «Молочный комбинат-5»", "purchases"),
        (None, "other"),
    ],
)
def test_empty_purpose_falls_back_to_counterparty(name, kind):
    cls = classify_text(None, name)
    assert cls.kind == kind
    assert cls.matched_by == ("none" if kind == "other" else "counterparty")


def test_nds_tail_does_not_trigger_tax():
    # «Без налога (НДС)» в хвосте назначения — не налоговый платёж.
    cls = classify_text("Оплата по счету № 1 от 01.05.2025 за продукцию. Без налога (НДС)", None)
    assert cls.kind == "purchases"


def test_every_kind_maps_to_backend_category():
    backend = {"sales", "purchases", "payroll", "rent", "tax", "fees", "loan", "transfer", "other"}
    assert {category for _, category in KINDS.values()} <= backend


def _op(day: date, rub: int, purpose: str, direction: str = "out") -> Operation:
    return Operation(
        "C900",
        f"op-{day}-{rub}",
        day,
        rub * 100,
        direction,  # type: ignore[arg-type]
        None,
        "ООО «Х»",
        purpose,
        None,
    )


def test_classify_outflow_rejects_incoming():
    with pytest.raises(ValueError):
        classify_outflow(_op(date(2025, 5, 1), 1, "Оплата", direction="in"))


def test_summarize_outflows_window_and_shares():
    as_of = date(2025, 6, 30)
    ops = [
        _op(date(2025, 6, 28), 300, "ЕНП"),
        _op(date(2025, 6, 10), 500, "Оплата по счету № 1 от 01.06.2025 за товар"),
        _op(date(2025, 6, 5), 200, "Выплата дивидендов за 1 квартал 2025 г."),
        _op(date(2025, 3, 1), 999, "ЕНП"),  # вне окна 90 дней
        _op(date(2025, 7, 1), 999, "ЕНП"),  # после среза — не видим
        _op(date(2025, 6, 1), 999, "Оплата", direction="in"),  # поступление не считаем
    ]
    s = summarize_outflows(ops, as_of)
    assert s["total_minor"] == 100_000
    assert s["by_flexibility_minor"] == {"flexible": 50_000, "hard": 30_000, "owner": 20_000}
    assert s["share_by_flexibility"]["owner"] == 0.2
    assert s["by_kind_minor"]["tax"] == 30_000
