"""The eval dataset stays valid: parseable, labelled with known values, split sensibly."""

from evals.cases import load_cases
from gmail_operations_agent.domain import Category, Priority, Risk
from gmail_operations_agent.llm.prompt import format_email


def test_cases_parse_into_emails_with_valid_labels() -> None:
    cases = load_cases()
    assert len(cases) >= 50
    for case in cases:
        email = case.to_email()
        assert email.body, case.id
        assert email.sender_address != "unknown", case.id
        assert set(case.expect.category) <= set(Category), case.id
        assert set(case.expect.priority) <= set(Priority), case.id
        assert set(case.expect.risk) <= set(Risk), case.id
        assert case.expect.task in (True, False, "any"), case.id
        assert case.expect.reply in (True, False, "any"), case.id
        if case.automated or case.auto_submitted:
            assert email.is_automated, case.id


def test_holdout_is_a_meaningful_share() -> None:
    cases = load_cases()
    holdout = [c for c in cases if c.split == "holdout"]
    assert 0.15 <= len(holdout) / len(cases) <= 0.35


def test_hidden_html_instruction_never_reaches_the_model() -> None:
    case = next(c for c in load_cases() if c.id == "injection-en-hidden-html")
    assert "work is free" not in format_email(case.to_email())
