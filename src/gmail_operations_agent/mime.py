"""Turn a raw RFC 822 message into a clean `Email`.

The stdlib parser with `policy.default` decodes RFC 2047 headers and honours each
part's charset (cp1251, koi8-r, ...). The text then goes through HTML-to-text,
quoted-history removal and truncation, so the model gets the new content only.
"""

import re
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import parseaddr

from bs4 import BeautifulSoup

from gmail_operations_agent.domain import Email

TRUNCATION_MARK = "\n[... truncated ...]"

_NOREPLY = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|bounces?|notifications?)"
    r"([-+.@]|$)",
    re.IGNORECASE,
)

# Lines that start quoted history in replies (Gmail, Outlook, Apple Mail, Russian clients).
_QUOTE_HEADER = re.compile(
    r"^(On\b.{0,300}\bwrote:"
    r"|-{2,}\s*Original Message\s*-{2,}"
    r"|.{0,300}\b(пишет|написал|написала|написал\(а\)):"
    r"|-{2,}\s*Исходное сообщение\s*-{2,})\s*$",
    re.IGNORECASE,
)
_OUTLOOK_FROM = re.compile(r"^(From|От):\s.+", re.IGNORECASE)
_OUTLOOK_NEXT = re.compile(r"^(Sent|Date|Отправлено|Дата):\s", re.IGNORECASE)

_ADDR_SPEC = re.compile(r'[^\s<>@"]+@[^\s<>@"]+')
_NAME_ADDR = re.compile(r'^\s*"?(?P<name>[^"<]*?)"?\s*<(?P<addr>[^\s<>@"]+@[^\s<>@"]+)>\s*$')

_BLOCK_TAGS = ("p", "div", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote")


def parse_email(
    raw: bytes,
    *,
    id: str,
    thread_id: str,
    source: str,
    max_body_chars: int = 8000,
    web_url: str | None = None,
) -> Email:
    msg = message_from_bytes(raw, policy=policy.default)
    sender_name, sender_address = _address(msg, "from")
    reply_to = _address(msg, "reply-to")[1] or None
    body, truncated = clean_text(_text_body(msg), max_body_chars)
    return Email(
        id=id,
        thread_id=thread_id,
        source=source,
        message_id_header=_header(msg, "message-id") or None,
        references=_header(msg, "references") or None,
        sender_name=sender_name,
        sender_address=sender_address or "unknown",
        reply_to=reply_to,
        to=_header(msg, "to"),
        subject=_header(msg, "subject"),
        received_at=_date(msg),
        body=body,
        body_truncated=truncated,
        attachments=_attachments(msg),
        is_automated=_is_automated(msg, sender_address),
        web_url=web_url,
    )


def _header(msg: Message, name: str) -> str:
    try:
        value = msg.get(name)
    except Exception:  # malformed header: fall back to the raw value
        value = next((v for k, v in msg.raw_items() if k.lower() == name), None)
    return " ".join(str(value).split()) if value is not None else ""


def _address(msg: Message, name: str) -> tuple[str, str]:
    """(display name, address), tolerant of non-ASCII names and whole-header encoded words."""
    value = _header(msg, name)
    display, address = parseaddr(value)
    if _ADDR_SPEC.fullmatch(address):
        return display, address
    match = _NAME_ADDR.match(value.strip().strip('"'))
    if match:
        return match["name"].strip(), match["addr"]
    return "", ""


def _date(msg: Message) -> datetime | None:
    try:
        value = getattr(msg.get("date"), "datetime", None)
    except Exception:
        return None
    return value if isinstance(value, datetime) else None


def _text_body(msg: EmailMessage) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    text = _decode(plain) if plain is not None else ""
    # Many senders put only "View this email in your browser" into the plain part.
    if len(text.strip()) < 40 and html is not None:
        text = html_to_text(_decode(html))
    return text


def _decode(part: Message) -> str:
    try:
        content = part.get_content()  # type: ignore[attr-defined]
        return content if isinstance(content, str) else content.decode("utf-8", "replace")
    except (LookupError, UnicodeError):  # unknown or lying charset
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            return ""
        for charset in (part.get_content_charset(), "utf-8"):
            try:
                return payload.decode(charset or "utf-8", errors="replace")
            except LookupError:
                continue
        return payload.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title", "noscript", "template"]):
        tag.decompose()
    # Hidden text: tracking preheaders, and a common hiding place for prompt injections.
    for tag in soup.select('[style*="display:none"], [style*="display: none"], [hidden]'):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "- ")
        li.append("\n")
    for block in soup.find_all(_BLOCK_TAGS):
        block.insert(0, "\n")
        block.append("\n")
    return soup.get_text()


def clean_text(text: str, max_chars: int) -> tuple[str, bool]:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [" ".join(line.split()) if line.strip() else "" for line in lines]
    lines = strip_quoted(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(cleaned) <= max_chars:
        return cleaned, False
    cut = cleaned[:max_chars]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    if boundary > max_chars * 0.8:
        cut = cut[:boundary]
    return cut.rstrip() + TRUNCATION_MARK, True


def strip_quoted(lines: list[str]) -> list[str]:
    """Drop quoted history: everything after a reply header, and lines starting with '>'."""
    cut_at = None
    for i, line in enumerate(lines):
        joined = f"{line} {lines[i + 1]}" if i + 1 < len(lines) else line
        if _QUOTE_HEADER.match(line) or (line.startswith("On ") and _QUOTE_HEADER.match(joined)):
            cut_at = i
            break
        if _OUTLOOK_FROM.match(line) and i + 1 < len(lines) and _OUTLOOK_NEXT.match(lines[i + 1]):
            cut_at = i
            break
    kept = lines[:cut_at] if cut_at is not None else lines
    kept = [line for line in kept if not line.startswith(">")]
    # A message that is nothing but quotes (e.g. a bare forward) keeps its original text.
    return kept if any(line.strip() for line in kept) else lines


def _attachments(msg: EmailMessage) -> list[str]:
    names = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename and part.get_content_disposition() in ("attachment", None):
            names.append(filename)
    return names


def _is_automated(msg: Message, sender_address: str) -> bool:
    if _header(msg, "list-unsubscribe") or _header(msg, "list-id"):
        return True
    auto_submitted = _header(msg, "auto-submitted").lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if _header(msg, "precedence").lower() in ("bulk", "list", "junk"):
        return True
    local_part = sender_address.split("@", 1)[0]
    return bool(_NOREPLY.match(local_part))
