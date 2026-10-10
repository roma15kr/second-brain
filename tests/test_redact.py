import pytest

from kb.redact import iban_ok, luhn_ok, redact

VISA = "4111 1111 1111 1111"  # Luhn-valid test card
NOT_LUHN = "4111 1111 1111 1112"


def r(text):
    return redact(text)[0]


def test_redact_card_luhn_valid_redacted_invalid_kept():
    assert r(f"card {VISA} exp 12/27") == "card [REDACTED:card] exp 12/27"
    assert r("pay to 5375-4141-0000-0000") == "pay to 5375-4141-0000-0000"  # not Luhn-valid
    assert NOT_LUHN in r(f"card {NOT_LUHN}")
    assert luhn_ok("4111111111111111") and not luhn_ok("4111111111111112")


def test_card_rules_spare_tracking_and_order_numbers():
    ttn = "20450813456789"  # Nova Poshta TTN, 14 digits
    assert r(f"накладна {ttn}") == f"накладна {ttn}"
    assert r("order 1000000000000009") == "order 1000000000000009"  # Luhn-valid, prefix 1


@pytest.mark.parametrize(
    "text, secret",
    [
        ("login: admin, password: Zx9!qq2L", "Zx9!qq2L"),
        ("Пароль: Qwerty-2026!", "Qwerty-2026!"),
        ("пароль від wifi: k1tt3n_42", "k1tt3n_42"),
        ("пасс = s3cr3t", "s3cr3t"),
        ("pwd:hunter22", "hunter22"),
        ("db at postgres://kb:VeryS3cret@db:5432/kb", "VeryS3cret"),
    ],
)
def test_redact_password_context_en_uk_ru(text, secret):
    out = r(text)
    assert secret not in out
    assert "[REDACTED:password]" in out


def test_password_word_without_value_is_kept():
    assert r("я змінив пароль вчора") == "я змінив пароль вчора"


@pytest.mark.parametrize(
    "text",
    [
        "Your verification code is 482913",
        "Код підтвердження: 5521",
        "Ваш код: 77341",
        "OTP 9081 valid for 5 minutes",
        "G-842193 is your Google verification code",
        "PIN 4821",
    ],
)
def test_otp_codes_redacted(text):
    out = r(text)
    assert "[REDACTED:otp]" in out
    assert not any(c.isdigit() for c in out.replace("5 minutes", ""))


@pytest.mark.parametrize(
    "text",
    [
        "Код ЄДРПОУ 43210987",
        "код товару 55123",
        "Промокод 2026 на знижку",
        "код замовлення 778812",
    ],
)
def test_business_codes_kept(text):
    assert r(text) == text


def test_redact_keeps_phone_price_order_date():
    text = (
        "Call +380 98 534 1120, price 12 500 грн, order #4471, due 2026-10-15, TTN 59001234567890"
    )
    assert r(text) == text


@pytest.mark.parametrize(
    "token",
    [
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
        "sk-proj-AbCdEfGhIjKlMnOpQrStUvWx",
        "ghp_" + "a1B2" * 9,
        "github_pat_" + "A1b2C3d4E5" * 3,
        "xoxb-1234567890-abcdefghij",
        "AKIAIOSFODNN7EXAMPLE",
        "AIza" + "B" * 35,
        "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw0",
    ],
)
def test_redact_known_token_formats(token):
    out = r(f"here: {token} ok")
    assert token not in out and "[REDACTED:token]" in out


def test_context_tokens_and_bearer():
    assert "[REDACTED:token]" in r("api_key = 9f8e7d6c5b4a39281706f5e4")
    assert r("Authorization: Bearer abcdefghijklmnopqrstuvwx").endswith("Bearer [REDACTED:token]")


def test_private_key_block():
    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n-----END OPENSSH PRIVATE KEY-----"
    assert r(f"key:\n{pem}\nthanks") == "key:\n[REDACTED:private_key]\nthanks"


def test_iban_with_checksum():
    iban = "UA213223130000026007233566001"
    assert iban_ok(iban)
    assert r(f"IBAN {iban}") == "IBAN [REDACTED:iban]"
    assert r("UA213223130000026007233566002 typo") == "UA213223130000026007233566002 typo"


def test_spans_reported():
    text, spans = redact("password: abc12345 and card 4111111111111111")
    assert [s.kind for s in spans] == ["password", "card"]
    assert text == "password: [REDACTED:password] and card [REDACTED:card]"


@pytest.mark.parametrize(
    "text, secret",
    [
        ("037402 is your verification code", "037402"),
        ("5521 — ваш код для входу", "5521"),
        ("Enter this code on the login verification page. GE5JA2 Your code", "GE5JA2"),
        ("Here is the code you requested: 9E7EYS", "9E7EYS"),
    ],
)
def test_more_otp_shapes(text, secret):
    out = r(text)
    assert secret not in out and "[REDACTED:otp]" in out


@pytest.mark.parametrize(
    "text, secret",
    [
        ("Логин пользователя demo Пароль Ab3kQ9xYz2Lm7Pq", "Ab3kQ9xYz2Lm7Pq"),
        (
            "Логин director Пароль (не я, ии такой нагенерировал) Demo!40ca59902af08f96",
            "Demo!40ca59902af08f96",
        ),
        ("password for the router 12345678", "12345678"),
        ("пароль от вайфая: kitten_42", "kitten_42"),
    ],
)
def test_passwords_without_separator(text, secret):
    out = r(text)
    assert secret not in out and "[REDACTED:password]" in out


@pytest.mark.parametrize(
    "text",
    [
        "Можно сделать админку + пароль",
        "передать почта+ пароль",
        "TikTok Ads code review on Monday",
        "код ЄДРПОУ AB1234 (not a secret)",
        "пароль змінили минулої весни",
    ],
)
def test_loose_rules_leave_plain_text(text):
    assert r(text) == text
