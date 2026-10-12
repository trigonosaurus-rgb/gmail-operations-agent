"""Deterministic rules applied after the model: code decides what is allowed to happen.

The model proposes; these rules have the final say. They are cheap, testable and
do not depend on the model resisting a cleverly written email.
"""

from gmail_operations_agent.domain import (
    ACTION_ORDER,
    ActionKind,
    Category,
    Email,
    Risk,
    Triage,
)

_NO_REPLY_CATEGORIES = {Category.NEWSLETTER, Category.NOTIFICATION, Category.SPAM}


def apply_guardrails(email: Email, triage: Triage) -> tuple[Triage, list[str]]:
    """Return the triage with unsafe proposals removed, plus notes explaining why."""
    notes: list[str] = []
    task, reply = triage.task, triage.reply
    risky = triage.risk != Risk.NONE

    if reply:
        if email.is_automated:
            reply = None
            notes.append("Reply draft dropped: the sender is automated or a mailing list.")
        elif risky:
            reply = None
            notes.append(f"Reply draft dropped: risk is {triage.risk.value}.")
        elif triage.category in _NO_REPLY_CATEGORIES:
            reply = None
            notes.append(f"Reply draft dropped: category {triage.category.value} gets no replies.")
    if task and risky:
        task = None
        notes.append(f"Task dropped: risk is {triage.risk.value}.")

    return triage.model_copy(update={"task": task, "reply": reply}), notes


def plan_actions(triage: Triage, enabled: set[ActionKind]) -> list[ActionKind]:
    """Which enabled actions apply to this email, in execution order."""
    wanted = {ActionKind.SHEETS_ROW, ActionKind.MARK_PROCESSED}
    if triage.task:
        wanted.add(ActionKind.NOTION_TASK)
    if triage.reply:
        wanted.add(ActionKind.GMAIL_DRAFT)
    return [kind for kind in ACTION_ORDER if kind in wanted and kind in enabled]
