import pytest

from app.modules.pulse.leaks.money import parse_amount_minor, parse_commission


@pytest.mark.parametrize(
    ("text", "minor"),
    [("2861-52", 286152), ("1 234.56", 123456), ("1234,56", 123456), ("0-05", 5), ("12 000.00", 1200000)],
)
def test_parse_amount_minor(text, minor):
    assert parse_amount_minor(text) == minor


@pytest.mark.parametrize("text", ["4424", "12.5", "abc", ""])
def test_parse_amount_minor_rejects(text):
    with pytest.raises(ValueError):
        parse_amount_minor(text)


def test_card_commission_from_acquiring_purpose():
    c = parse_commission(
        "Зачисление средств по операциям эквайринга. Мерчант №4814886. Дата "
        "реестра 28.01.2025. Сумма операций 2861-52, комиссия 51-47, возврат "
        "покупки 0.00. НДС не облагается"
    )
    assert (c.channel, c.gross_minor, c.fee_minor) == ("card", 286152, 5147)


def test_sbp_commission_with_spaces_in_amount():
    c = parse_commission(
        "Зачисление по операциям оплаты через СБП (QR-код) за 28.01.2025. "
        "Сумма 11 551.73, комиссия 51.88. НДС не облагается"
    )
    assert (c.channel, c.gross_minor, c.fee_minor) == ("sbp", 1155173, 5188)


@pytest.mark.parametrize(
    "purpose",
    [
        None,
        "Оплата по УПД № 1 от 01.01.2025",
        "Зачисление средств по операциям эквайринга. Мерчант №1.",  # без суммы и комиссии
        "Зачисление по операциям оплаты через СБП. Сумма 10-00, комиссия 20-00.",
    ],  # комиссия > суммы
)
def test_parse_commission_absent_or_invalid(purpose):
    assert parse_commission(purpose) is None
