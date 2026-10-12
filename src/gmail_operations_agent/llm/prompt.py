"""Prompts live in versioned Markdown files; the version is stored with every LLM call."""

from dataclasses import dataclass
from importlib.resources import files
from string import Template

from gmail_operations_agent.domain import Email


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    template: Template

    def render(self, **values: str) -> str:
        return self.template.substitute(values)


def load_prompt(name: str) -> Prompt:
    text = files("gmail_operations_agent.llm.prompts").joinpath(f"{name}.md").read_text("utf-8")
    meta: dict[str, str] = {}
    if text.startswith("---\n"):
        header, text = text[4:].split("\n---\n", 1)
        for line in header.splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return Prompt(name=name, version=meta.get("version", "unversioned"), template=Template(text))


def format_email(email: Email) -> str:
    """The email as untrusted data inside explicit delimiters."""
    fields = [
        f"From: {email.sender_display}",
        f"Reply-To: {email.reply_to}" if email.reply_to else None,
        f"To: {email.to}" if email.to else None,
        f"Date: {email.received_at.isoformat()}" if email.received_at else None,
        f"Subject: {email.subject}",
        f"Attachments: {', '.join(email.attachments)}" if email.attachments else None,
        f"Automated sender: {'yes' if email.is_automated else 'no'}",
        f"Body truncated: {'yes' if email.body_truncated else 'no'}",
    ]
    header = "\n".join(field for field in fields if field)
    return f"<email>\n{_defuse(header)}\n\n{_defuse(email.body)}\n</email>"


def _defuse(text: str) -> str:
    # The sender must not be able to close the data block and continue as "instructions".
    return text.replace("</email", "</ email").replace("<email", "< email")
