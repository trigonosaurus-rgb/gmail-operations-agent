"""Load eval cases and turn each into a real RFC 822 message, parsed like production mail."""

import tomllib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any, Literal

from gmail_operations_agent.domain import Email
from gmail_operations_agent.mime import parse_email

CASES_FILE = Path(__file__).parent / "cases.toml"

Flag = bool | Literal["any"]


@dataclass(frozen=True)
class Expectation:
    category: list[str]
    priority: list[str]
    risk: list[str]
    task: Flag
    reply: Flag


@dataclass(frozen=True)
class Case:
    id: str
    split: str
    lang: str
    sender: str
    subject: str
    body: str
    expect: Expectation
    html: bool = False
    automated: bool = False
    auto_submitted: bool = False
    attachments: list[str] = field(default_factory=list)

    def to_email(self) -> Email:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = "Alex <alex@example.com>"
        msg["Subject"] = self.subject
        msg["Date"] = formatdate(1_791_795_600, localtime=False)  # 2026-10-12 09:00 UTC
        msg["Message-ID"] = f"<{self.id}@evals.local>"
        if self.automated:
            msg["List-Unsubscribe"] = "<https://example.com/unsubscribe>"
        if self.auto_submitted:
            msg["Auto-Submitted"] = "auto-replied"
        body = self.body.strip()
        if self.html:
            msg.set_content(body, subtype="html")
        else:
            msg.set_content(body)
        for name in self.attachments:
            msg.add_attachment(b"%PDF-1.4 placeholder", "application", "pdf", filename=name)
        return parse_email(msg.as_bytes(), id=self.id, thread_id=self.id, source="eval")


def _list(value: Any) -> list[str]:
    return list(value) if isinstance(value, list) else [value]


def load_cases(split: str = "all") -> list[Case]:
    data = tomllib.loads(CASES_FILE.read_text("utf-8"))
    cases = []
    for raw in data["case"]:
        expect = raw["expect"]
        case = Case(
            id=raw["id"],
            split=raw["split"],
            lang=raw["lang"],
            sender=raw["from"],
            subject=raw["subject"],
            body=raw["body"],
            html=raw.get("html", False),
            automated=raw.get("automated", False),
            auto_submitted=raw.get("auto_submitted", False),
            attachments=raw.get("attachments", []),
            expect=Expectation(
                category=_list(expect["category"]),
                priority=_list(expect["priority"]),
                risk=_list(expect["risk"]),
                task=expect["task"],
                reply=expect["reply"],
            ),
        )
        if split in ("all", case.split):
            cases.append(case)
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids in cases.toml")
    return cases
