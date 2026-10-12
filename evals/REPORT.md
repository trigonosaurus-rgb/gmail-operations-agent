# Eval report (dev split)

Generated 2026-10-12 by `python -m evals.report --split dev`, current prompt `triage-v2`; each row names the prompt it ran with. Column definitions: [evals/README.md](README.md).

| Run | Model, effort, prompt | Cases | Errors | Category | Priority | Risk | Task F1 | Reply F1 | All fields | Unsafe | False alarms | Good drafts | $ / 1k emails | p50 / p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| luna-low | gpt-6-luna, low, triage-v1 | 41 | 0 | 100% | 95% | 100% | 0.97 | 1.00 | 93% | 0 / 8 | 0 / 31 | 74% | $0.11 | 4.1 / 7.1 |
| luna-low-v2 | gpt-6-luna, low, triage-v2 | 41 | 0 | 100% | 98% | 100% | 1.00 | 1.00 | 98% | 0 / 8 | 0 / 31 | 94% | $0.12 | 2.4 / 3.7 |
| luna-none | gpt-6-luna, none, triage-v1 | 41 | 0 | 98% | 98% | 100% | 0.97 | 1.00 | 93% | 0 / 8 | 0 / 31 | 68% | $0.09 | 2.5 / 7.1 |
| luna-none-v2 | gpt-6-luna, none, triage-v2 | 41 | 0 | 98% | 100% | 100% | 1.00 | 1.00 | 98% | 0 / 8 | 0 / 31 | 90% | $0.10 | 2.1 / 3.3 |
| sol-low | gpt-6.1-sol, low, triage-v1 | 41 | 0 | 100% | 98% | 100% | 0.97 | 1.00 | 95% | 0 / 8 | 0 / 31 | – | $2.06 | 4.0 / 6.5 |
| sol-medium | gpt-6.1-sol, medium, triage-v1 | 41 | 0 | 100% | 98% | 100% | 0.97 | 1.00 | 95% | 0 / 8 | 0 / 31 | 68% | $2.49 | 4.4 / 8.6 |
| sol-medium-v2 | gpt-6.1-sol, medium, triage-v2 | 41 | 0 | 100% | 100% | 100% | 1.00 | 1.00 | 100% | 0 / 8 | 0 / 31 | 100% | $2.55 | 5.0 / 9.0 |
