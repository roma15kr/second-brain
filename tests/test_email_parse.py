from kb.email_parse import html_to_text, parse
from tests.fakes import make_email


def test_parse_plain_email_fields():
    p = parse(make_email("Budget Q4", "Let's keep 5000 for Meta ads", message_id="<a1@x>"))
    assert p.subject == "Budget Q4"
    assert p.sender == "oleh@quokka.example"
    assert p.recipients == ["me@example.com"]
    assert "5000 for Meta ads" in p.body
    assert p.message_id == "<a1@x>"
    assert p.date is not None and p.date.year == 2026


def test_parse_prefers_plain_and_lists_attachments():
    raw = make_email(
        "Contract", "See attached", html="<p>HTML version</p>", attachment="contract.pdf"
    )
    p = parse(raw)
    assert "See attached" in p.body
    assert "HTML version" not in p.body
    assert p.attachments == ["contract.pdf"]


def test_html_to_text_drops_scripts_and_styles():
    text = html_to_text("<style>x{}</style><p>Hello</p><script>alert(1)</script><div>World</div>")
    assert "Hello" in text and "World" in text
    assert "alert" not in text and "x{}" not in text
