"""Разбор назначений на формулировках, встречающихся в датасете (цифры выдуманы)."""

from datetime import date

import pytest

from app.modules.pulse.advisor.documents import non_operating_reason, parse_document, parse_purpose


@pytest.mark.parametrize(
    ("purpose", "kind", "number", "doc_date"),
    [
        ("Оплата по УПД № 279 от 19.08.2024. НДС не облагается", "upd", "279", date(2024, 8, 19)),
        ("Оплата по УПД № 12 от 01.02.2025. В т.ч. НДС 20% - 1 000.00", "upd", "12", date(2025, 2, 1)),
        # «по счету 307» без знака №, номер договора перед ним игнорируется.
        (
            "Оплата по договору № 386/18 по счету 307 от 07.10.2024 за перевозку груза.",
            "invoice",
            "307",
            date(2024, 10, 7),
        ),
        ("Оплата по счету № 55 от 3.11.2025 за товар по договору поставки.", "invoice", "55", date(2025, 11, 3)),
        ("Оплата по акту № А-7 от 15.01.2026", "act", "А-7", date(2026, 1, 15)),
        ("Оплата по товарной накладной № 9 от 10.03.2025", "waybill", "9", date(2025, 3, 10)),
    ],
)
def test_parse_document_found(purpose, kind, number, doc_date):
    doc = parse_document(purpose)
    assert doc is not None
    assert (doc.kind, doc.number, doc.doc_date) == (kind, number, doc_date)


@pytest.mark.parametrize(
    "purpose",
    [
        None,
        "",
        # Дата договора — не дата выставления, задержку от неё не считаем.
        "Окончательный расчет по договору № 15-3 от 02.04.2025. Без НДС",
        "Инкассированная выручка по сумке № 4411 от 05.05.2025. НДС не облагается",
        "Зачисление средств по операциям эквайринга. Мерчант №123. Дата реестра 01.01.2025.",
        "Перевод собственных средств на расчетный счет в АО «Банк-1». НДС не облагается",
        "Оплата по УПД № 5 от 31.02.2025",  # несуществующая дата
    ],
)
def test_parse_document_absent(purpose):
    assert parse_document(purpose) is None


def test_partial_and_prepayment_flags():
    info = parse_purpose("Частичная оплата по УПД № 296 от 02.09.2024. НДС не облагается.")
    assert info.partial and not info.prepayment and info.document is not None
    pre = parse_purpose("Предоплата по договору № 1-2 от 01.01.2025 на изготовление мебели")
    assert pre.prepayment and pre.document is None


@pytest.mark.parametrize(
    ("purpose", "reason"),
    [
        # Возврат содержит ссылку на документ, но это наши же деньги — не оплата клиента.
        ("Возврат платежа: неверно указаны реквизиты получателя. Оплата по УПД № 1 от 01.01.2025", "refund"),
        ("Перевод собственных средств с расчетного счета в АО «Банк-2».", "own_transfer"),
        ("Пополнение счета собственными средствами. НДС не облагается", "own_transfer"),
        ("Предоставление беспроцентного займа учредителем по договору № 1/2.", "loan"),
        ("Выдача кредита (транш) по договору кредитной линии № КЛ-1.", "loan"),
        ("Оплата по УПД № 279 от 19.08.2024", None),
        (None, None),
    ],
)
def test_non_operating_reason(purpose, reason):
    assert non_operating_reason(purpose) == reason
