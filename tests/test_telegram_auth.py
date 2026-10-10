from types import SimpleNamespace

from telethon.tl.types import auth

from kb.telegram_auth import describe_sent_code, render_qr


def sent(code_type, next_type=None, timeout=None):
    return SimpleNamespace(type=code_type, next_type=next_type, timeout=timeout)


def test_app_code_points_to_telegram_chat():
    text = describe_sent_code(sent(auth.SentCodeTypeApp(length=5)))
    assert "Telegram app" in text and "5 digits" in text


def test_email_code_shows_pattern():
    text = describe_sent_code(
        sent(auth.SentCodeTypeEmailCode(email_pattern="d***@gmail.com", length=6))
    )
    assert "login email d***@gmail.com" in text


def test_resend_option_names_next_method():
    text = describe_sent_code(sent(auth.SentCodeTypeApp(length=5), auth.CodeTypeSms(), timeout=60))
    assert "resend it by Sms after 60s" in text


def test_setup_email_required_is_explained():
    text = describe_sent_code(
        sent(
            auth.SentCodeTypeSetUpEmailRequired(
                apple_signin_allowed=False, google_signin_allowed=False
            )
        )
    )
    assert "login email to be set up" in text


def test_render_qr_is_text_block():
    block = render_qr("tg://login?token=abc")
    assert len(block.splitlines()) > 10
