# Evaluation harness

Measures the quality of each layer of the assistant against a curated golden
set, so changes can be judged by numbers instead of vibes. This is the safety
net every later change (retry logic, RAG tuning, auth) is validated against.

## Suites

| Suite | Measures | Metric | Needs |
|---|---|---|---|
| `routing` | intent router picks the right specialist | `accuracy` (≥ 0.85) | `LLM_API_KEY` |
| `retrieval` | RAG surfaces the doc that holds the answer | `hit@k` (≥ 0.8), `mrr` | built index (`make data`) |
| `groundedness` | end-to-end answer cites sources, stays in scope, refuses correctly | `pass_rate` (≥ 0.9) | `LLM_API_KEY` + index + DB |

Golden sets live in [`datasets/`](datasets) as JSONL (one case per line;
`//` comment lines allowed). Expected values are **human ground truth** — if
the system misses one, that is exactly the signal the eval exists to surface,
so fix the system before editing the golden answer.

## Running

```bash
make data                 # once: build the index + DB the suites read
export LLM_API_KEY=gsk_... # for routing / groundedness (retrieval needs no key)

make eval                 # all suites; retrieval-only if no key is set
python -m evals --suite retrieval          # single suite
python -m evals --suite retrieval --top-k 6
python -m evals --judge                    # add an LLM-as-judge groundedness score
python -m evals --json report.json -v      # machine-readable report + all cases
```

Suites that need a key are **skipped, not failed**, when `LLM_API_KEY` is
unset, so `make eval` still exercises retrieval offline. The process exits
non-zero if any suite that actually ran falls below its thresholds — enough to
gate a release check.

## Design notes

- Metric functions (`metrics.py`) and the answer-assertion engine
  (`suites.check_answer`) are pure and unit-tested offline in
  `tests/test_eval_metrics.py`, so the harness can't silently break.
- The `groundedness` suite runs the **real** orchestrator in-process against an
  in-memory MCP toolbox and the live LLM — the same path production uses.
- `--judge` adds a 1-5 groundedness score from an LLM grader. It is reported
  but **not** gated, because it is non-deterministic.
