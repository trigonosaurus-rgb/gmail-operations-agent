"""Export the demo's content from the eval set and its recorded runs. Free: no API calls.

    uv run python -m evals.export_demo

Writes src/gmail_operations_agent/demo/data.json: the seed inbox and the test-form
presets as parsed emails, each with the model output recorded by the chosen run.
"""

import json
from pathlib import Path
from typing import Any

from evals.cases import Case, load_cases
from evals.configs import OWNER_CONTEXT
from gmail_operations_agent.demo.data import DATA_FILE, PRESET_SPECS, SEED

RESULTS = Path(__file__).parent / "results"
# The configuration the demo runs live (see evals/REPORT.md), with prompt triage-v2.
RUNS = {"dev": "luna-low-v2", "holdout": "luna-low-v2-holdout"}
WORKING_LANGUAGE = "English"
_EMAIL_FIELDS = (
    "sender_name",
    "sender_address",
    "to",
    "subject",
    "body",
    "body_truncated",
    "attachments",
    "is_automated",
)


def _recorded(case: Case) -> dict[str, Any]:
    path = RESULTS / RUNS[case.split] / f"{case.id}.json"
    record = json.loads(path.read_text("utf-8"))
    if "triage" not in record:
        raise ValueError(f"{path} has no recorded triage")
    return {"triage": record["triage"], "usage": record["usage"]}


def build() -> dict[str, Any]:
    cases = {case.id: case for case in load_cases()}
    exported: dict[str, Any] = {}
    for case_id in [seed.case for seed in SEED] + [preset.case for preset in PRESET_SPECS]:
        case = cases[case_id]
        email = case.to_email().model_dump(mode="json")
        exported[case_id] = {
            "email": {field: email[field] for field in _EMAIL_FIELDS},
            **_recorded(case),
        }
    presets = []
    for spec in PRESET_SPECS:
        case = cases[spec.case]
        email = case.to_email()
        presets.append(
            {
                "id": spec.case,
                "label": spec.label,
                "sender_name": email.sender_name,
                "sender_address": email.sender_address,
                "subject": case.subject,
                "body": case.body.strip(),
            }
        )
    return {
        "owner_context": OWNER_CONTEXT,
        "working_language": WORKING_LANGUAGE,
        "presets": presets,
        "cases": exported,
    }


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    DATA_FILE.write_text(render(), "utf-8", newline="\n")
    print(f"Wrote {DATA_FILE}")


if __name__ == "__main__":
    main()
