"""Demo content: which eval cases seed the inbox, the test-form presets, and their recordings.

`data.json` is generated from the eval set and its recorded model outputs by
`python -m evals.export_demo`; a test keeps it in sync. Recorded outputs are replayed
for the seed inbox and for unchanged presets, so the demo works with no API key
and costs nothing until a visitor writes an email of their own.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from functools import cache
from pathlib import Path
from typing import Literal

from gmail_operations_agent.domain import Email, Triage, Usage
from gmail_operations_agent.mime import parse_email

DATA_FILE = Path(__file__).parent / "data.json"

OWNER_ADDRESS = "Alex <alex@example.com>"

Scenario = Literal["approve", "approve_and_fail"]


@dataclass(frozen=True)
class Seed:
    case: str
    minutes_ago: int
    # The demo approves a few emails on its own, so the inbox shows every state on the
    # first visit. "approve_and_fail" also makes the sandboxed Notion call fail once.
    scenario: Scenario | None = None


# Newest first, as the inbox shows them.
SEED: tuple[Seed, ...] = (
    Seed("lead-en-dental", 3),
    Seed("client-en-bot-down", 26),
    Seed("lead-ru-shop", 50),
    Seed("meeting-ru-invite", 73),
    Seed("client-ru-edits", 85),
    Seed("lead-de-agency", 97, "approve_and_fail"),
    Seed("phishing-en-bank-details", 116),
    Seed("injection-en-in-lead", 140),
    Seed("invoice-ru-schet", 158, "approve"),
    Seed("spam-ru-leads", 170),
    Seed("newsletter-en-ai-weekly", 186),
)


@dataclass(frozen=True)
class PresetSpec:
    case: str
    label: str


PRESET_SPECS: tuple[PresetSpec, ...] = (
    PresetSpec("lead-en-low-budget", "New lead"),
    PresetSpec("client-en-scope-creep", "Client request"),
    PresetSpec("invoice-en-overdue", "Overdue invoice"),
    PresetSpec("phishing-en-password", "Phishing"),
    PresetSpec("injection-en-urgent", "Prompt injection"),
)


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    sender_name: str
    sender_address: str
    subject: str
    body: str


@dataclass(frozen=True)
class Recording:
    triage: Triage
    usage: Usage


@dataclass(frozen=True)
class DemoData:
    owner_context: str
    working_language: str
    seed_emails: dict[str, dict[str, object]]  # case id -> Email fields without ids
    presets: list[Preset]
    recordings: dict[str, Recording]  # fingerprint -> recorded model output


def fingerprint(email: Email) -> str:
    """Identifies an email's content for replay, ignoring ids, dates and whitespace."""
    text = "\n".join(
        [
            email.sender_address.lower(),
            " ".join(email.subject.split()),
            " ".join(email.body.split()),
        ]
    )
    return hashlib.sha256(text.encode()).hexdigest()


def compose_email(
    *,
    id: str,
    sender_name: str,
    sender_address: str,
    subject: str,
    body: str,
    received_at: datetime | None = None,
    max_body_chars: int = 8000,
) -> Email:
    """Build a real RFC 822 message and parse it the way Gmail mail is parsed."""
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name, sender_address))
    msg["To"] = OWNER_ADDRESS
    msg["Subject"] = subject
    msg["Date"] = format_datetime(received_at or datetime.now(UTC))
    msg["Message-ID"] = f"<{id}@demo.local>"
    msg.set_content(body.replace("\r\n", "\n").strip())
    return parse_email(
        msg.as_bytes(), id=id, thread_id=id, source="demo", max_body_chars=max_body_chars
    )


@cache
def load() -> DemoData:
    raw = json.loads(DATA_FILE.read_text("utf-8"))
    recordings: dict[str, Recording] = {}
    seed_emails: dict[str, dict[str, object]] = {}
    for case_id, item in raw["cases"].items():
        email = Email.model_validate(
            {"id": case_id, "thread_id": case_id, "source": "demo", **item["email"]}
        )
        recordings[fingerprint(email)] = Recording(
            triage=Triage.model_validate(item["triage"]),
            usage=Usage.model_validate(item["usage"]),
        )
        seed_emails[case_id] = item["email"]
    presets = [Preset(**preset) for preset in raw["presets"]]
    return DemoData(
        owner_context=raw["owner_context"],
        working_language=raw["working_language"],
        seed_emails=seed_emails,
        presets=presets,
        recordings=recordings,
    )
