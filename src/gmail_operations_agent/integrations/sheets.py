"""Google Sheets log: one row per processed email."""

from datetime import UTC, datetime

from gmail_operations_agent.domain import ActionKind, ActionResult, Email, Triage
from gmail_operations_agent.integrations.google_api import NUM_RETRIES, GoogleApi

HEADER = [
    "Processed at",
    "Received at",
    "From",
    "Subject",
    "Category",
    "Priority",
    "Risk",
    "Summary",
    "Link",
    "Message ID",
]
_LAST_COLUMN = chr(ord("A") + len(HEADER) - 1)  # J
_ID_COLUMN = _LAST_COLUMN


def build_row(email: Email, triage: Triage, processed_at: datetime) -> list[str]:
    return [
        processed_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M"),
        email.received_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M") if email.received_at else "",
        email.sender_display,
        email.subject,
        triage.category.value,
        triage.priority.value,
        triage.risk.value,
        triage.summary,
        email.web_url or "",
        email.id,
    ]


class SheetsSink:
    kind = ActionKind.SHEETS_ROW

    def __init__(self, api: GoogleApi, spreadsheet_id: str, tab: str) -> None:
        self._api = api
        self._spreadsheet_id = spreadsheet_id
        self._tab = tab
        self._header_checked = False

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        return {"columns": HEADER, "row": build_row(email, triage, datetime.now(UTC))}

    async def _ensure_header(self) -> None:
        if self._header_checked:
            return
        response = await self._api.call(
            lambda: (
                self._api.sheets()
                .spreadsheets()
                .values()
                .get(spreadsheetId=self._spreadsheet_id, range=f"{self._tab}!A1:{_LAST_COLUMN}1")
                .execute(num_retries=NUM_RETRIES)
            )
        )
        if not response.get("values"):
            await self._api.call(
                lambda: (
                    self._api.sheets()
                    .spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self._spreadsheet_id,
                        range=f"{self._tab}!A1:{_LAST_COLUMN}1",
                        valueInputOption="RAW",
                        body={"values": [HEADER]},
                    )
                    .execute(num_retries=NUM_RETRIES)
                )
            )
        self._header_checked = True

    async def find_existing(self, email: Email) -> ActionResult | None:
        response = await self._api.call(
            lambda: (
                self._api.sheets()
                .spreadsheets()
                .values()
                .get(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{self._tab}!{_ID_COLUMN}:{_ID_COLUMN}",
                )
                .execute(num_retries=NUM_RETRIES)
            )
        )
        for index, row in enumerate(response.get("values", []), start=1):
            if row and row[0] == email.id:
                return ActionResult(external_id=f"{self._tab}!A{index}:{_LAST_COLUMN}{index}")
        return None

    async def execute(self, email: Email, triage: Triage) -> ActionResult:
        await self._ensure_header()
        row = build_row(email, triage, datetime.now(UTC))
        # RAW, not USER_ENTERED: a subject like "=IMPORTXML(...)" from a stranger must stay
        # text, not become a formula; "1/2" must not turn into a date.
        response = await self._api.call(
            lambda: (
                self._api.sheets()
                .spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{self._tab}!A:{_LAST_COLUMN}",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute()
            )  # no client retries for a non-idempotent append
        )
        updated_range = response.get("updates", {}).get("updatedRange")
        return ActionResult(
            external_id=updated_range,
            url=f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}",
            preview={"columns": HEADER, "row": row},
        )
