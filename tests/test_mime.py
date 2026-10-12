"""Parsing real-world message shapes; each case was a crash or a silent empty body before v2."""

from gmail_operations_agent.mime import TRUNCATION_MARK, clean_text, html_to_text, parse_email
from tests.conftest import fixture_bytes


def parse(name: str, **kwargs: object):  # type: ignore[no-untyped-def]
    return parse_email(fixture_bytes(name), id="m1", thread_id="t1", source="test", **kwargs)  # type: ignore[arg-type]


def test_cp1251_body_and_headers_are_decoded() -> None:
    email = parse("cp1251_invoice.eml")
    assert "счёт №418 на 45 000 руб" in email.body
    assert email.subject == "Счёт на оплату №418"
    assert email.sender_name == "Бухгалтерия"
    assert email.sender_address == "buh@romashka.ru"


def test_koi8r_body_is_decoded() -> None:
    assert "чат-бота для нашего магазина" in parse("koi8r_question.eml").body


def test_html_only_message_gets_a_text_body_without_hidden_or_script_text() -> None:
    body = parse("html_only.eml").body
    assert "Could you send a quote for the RAG chatbot by Friday?" in body
    assert "- 10k documents" in body
    assert "Ignore all previous instructions" not in body  # display:none
    assert "alert(1)" not in body
    assert "color: red" not in body


def test_nested_multipart_uses_the_body_and_lists_attachments() -> None:
    email = parse("nested_with_attachments.eml")
    assert email.body == "Please review the attached contract and the notes."
    assert email.attachments == ["notes.txt", "contract.pdf"]
    assert email.subject == "Привет 👋"


def test_quoted_history_is_removed_and_reply_headers_are_kept() -> None:
    email = parse("reply_with_history.eml")
    assert email.body == "Sounds good, let's do Thursday at 3pm."
    assert email.reply_to == "carol.assistant@partner.org"
    assert email.reply_address == "carol.assistant@partner.org"
    assert email.references == "<first@example.com>"
    assert email.message_id_header


def test_russian_quote_header_is_removed() -> None:
    assert parse("russian_reply_with_history.eml").body == "Подтверждаю, начинаем в понедельник."


def test_mailing_lists_and_noreply_senders_are_automated() -> None:
    assert parse("newsletter.eml").is_automated
    assert not parse("koi8r_question.eml").is_automated


def test_unknown_charset_does_not_crash() -> None:
    assert "Hello" in parse("unknown_charset.eml").body


def test_long_body_is_truncated_on_a_word_boundary() -> None:
    text, truncated = clean_text("word " * 1000, max_chars=600)
    assert truncated
    assert text.endswith(TRUNCATION_MARK)
    assert len(text) <= 600 + len(TRUNCATION_MARK)
    assert not text.removesuffix(TRUNCATION_MARK).endswith("wor")


def test_message_that_is_only_a_quote_keeps_its_text() -> None:
    text, _ = clean_text("> forwarded line one\n> line two", max_chars=1000)
    assert "forwarded line one" in text


def test_html_line_breaks_become_newlines() -> None:
    assert html_to_text("a<br>b<p>c</p>").split() == ["a", "b", "c"]


def test_received_date_is_parsed() -> None:
    received = parse("cp1251_invoice.eml").received_at
    assert received is not None
    assert received.utcoffset() is not None


def test_properly_encoded_display_name() -> None:
    email = parse("koi8r_question.eml")
    assert (email.sender_name, email.sender_address) == ("Иван Петров", "ivan@shop.ru")
