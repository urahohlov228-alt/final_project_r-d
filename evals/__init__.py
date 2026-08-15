"""Offline-friendly evaluation harness for the HR assistant.

Three suites, each measuring one layer of the pipeline against a curated
golden set (`datasets/`):

- routing      — does the intent router pick the right specialist?
- retrieval    — does RAG surface the document that actually holds the answer?
- groundedness — does the end-to-end answer cite sources, stay in scope and
                 refuse what it should?

Run with `python -m evals` (or `make eval`). Metric functions live in
`metrics.py` and are pure, so the harness itself is unit-tested offline in
`tests/test_eval_metrics.py`.
"""
