"""Run one model configuration over the cases. PAID: calls the OpenAI API.

    uv run python -m evals.run --config luna-low                # dev split
    uv run python -m evals.run --config luna-low --split holdout
    uv run python -m evals.run --config sol-low --limit 5      # quick pilot
    uv run python -m evals.run --config luna-low --name luna-low-v2   # after a prompt change

Results go to evals/results/<name>/<case>.json (name defaults to the config), with the
config and prompt version in meta.json. Existing results are skipped, so an interrupted
run resumes. The run stops when --max-usd is spent.
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from evals.cases import Case, load_cases
from evals.configs import CONFIGS, OWNER_CONTEXT, TODAY
from gmail_operations_agent.config import Settings
from gmail_operations_agent.errors import AgentError
from gmail_operations_agent.llm.openai_provider import OpenAIProvider
from gmail_operations_agent.rules import apply_guardrails

RESULTS = Path(__file__).parent / "results"


async def run_case(provider: OpenAIProvider, case: Case, out: Path) -> float:
    email = case.to_email()
    record: dict[str, object] = {"case": case.id, "model": provider.model}
    try:
        outcome = await provider.triage(email)
    except AgentError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        cost = 0.0
    else:
        final, notes = apply_guardrails(email, outcome.triage)
        record |= {
            "triage": outcome.triage.model_dump(mode="json"),
            "final": final.model_dump(mode="json"),
            "notes": notes,
            "usage": outcome.usage.model_dump(mode="json"),
        }
        cost = outcome.usage.cost_usd or 0.0
    text = json.dumps(record, ensure_ascii=False, indent=2)
    await asyncio.to_thread(out.write_text, text, "utf-8", newline="\n")
    status = "error" if "error" in record else "ok"
    print(f"  {case.id:32} {status:5} ${cost:.5f}")
    return cost


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, choices=sorted(CONFIGS))
    parser.add_argument("--name", help="results folder; defaults to the config name")
    parser.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-usd", type=float, default=2.0)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    settings = Settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set")
        return 2
    config = CONFIGS[args.config]
    provider = OpenAIProvider(
        settings.openai_api_key.get_secret_value(),
        config.model,
        reasoning_effort=config.effort,
        owner_context=OWNER_CONTEXT,
        today=lambda: date.fromisoformat(TODAY),
    )
    out_dir = RESULTS / (args.name or args.config)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"config": args.config, "prompt_version": provider.prompt_version}
    meta_file = out_dir / "meta.json"
    if meta_file.exists() and json.loads(meta_file.read_text("utf-8")) != meta:
        print(f"{out_dir} holds results for {meta_file.read_text('utf-8')}; use another --name")
        return 2
    meta_file.write_text(json.dumps(meta), "utf-8", newline="\n")
    cases = [c for c in load_cases(args.split) if not (out_dir / f"{c.id}.json").exists()]
    if args.limit:
        cases = cases[: args.limit]
    print(f"{args.config}: {len(cases)} case(s) to run, budget ${args.max_usd:.2f}")

    spent = 0.0
    semaphore = asyncio.Semaphore(args.concurrency)

    async def guarded(case: Case) -> None:
        nonlocal spent
        async with semaphore:
            if spent >= args.max_usd:
                return
            # Not `spent += await ...`: that reads `spent` before the await and
            # overwrites what other tasks added in the meantime.
            cost = await run_case(provider, case, out_dir / f"{case.id}.json")
            spent += cost

    await asyncio.gather(*(guarded(case) for case in cases))
    print(f"spent ${spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
