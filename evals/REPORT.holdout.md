# Eval report (holdout split)

Generated 2026-10-12 by `python -m evals.report --split holdout`, current prompt `triage-v2`; each row names the prompt it ran with. Column definitions: [evals/README.md](README.md).

| Run | Model, effort, prompt | Cases | Errors | Category | Priority | Risk | Task F1 | Reply F1 | All fields | Unsafe | False alarms | Good drafts | $ / 1k emails | p50 / p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| luna-low-v2-holdout | gpt-6-luna, low, triage-v2 | 14 | 0 | 100% | 100% | 100% | 1.00 | 1.00 | 100% | 0 / 3 | 0 / 10 | 100% | $0.11 | 2.2 / 3.6 |
| sol-medium-v2-holdout | gpt-6.1-sol, medium, triage-v2 | 14 | 0 | 100% | 100% | 100% | 0.92 | 1.00 | 93% | 0 / 3 | 0 / 10 | 100% | $2.51 | 4.8 / 7.4 |
