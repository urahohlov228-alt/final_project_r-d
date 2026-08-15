"""Eval CLI: `python -m evals [--suite ...]`.

Runs the selected suites against the real system and prints a per-suite report
with an overall PASS/FAIL. Suites that need an LLM are skipped (not failed)
when no LLM_API_KEY is configured, so `make eval` still exercises retrieval
offline. Exit code is non-zero if any suite that actually ran fell below its
thresholds — enough to gate a change in CI or a pre-release check.
"""

import argparse
import asyncio
import json
import sys

from hr_assistant.agents import OpenAICompatibleLLM
from hr_assistant.config import get_settings

from . import data, suites
from .suites import SuiteResult

ALL_SUITES = ["routing", "retrieval", "groundedness"]
NEEDS_LLM = {"routing", "groundedness"}


async def _run(args) -> tuple[list[SuiteResult], list[str]]:
    settings = get_settings()
    selected = ALL_SUITES if args.suite == "all" else [args.suite]

    llm = None
    if set(selected) & NEEDS_LLM and settings.llm_enabled:
        llm = OpenAICompatibleLLM(settings)

    results: list[SuiteResult] = []
    skipped: list[str] = []
    for name in selected:
        if name in NEEDS_LLM and not settings.llm_enabled:
            skipped.append(name)
            continue
        if name == "routing":
            dataset = data.load_jsonl("routing.jsonl")
            results.append(await suites.run_routing(llm, settings, dataset))
        elif name == "retrieval":
            results.append(
                suites.run_retrieval(settings, data.load_jsonl("retrieval.jsonl"), top_k=args.top_k)
            )
        elif name == "groundedness":
            results.append(
                await suites.run_groundedness(
                    llm, settings, data.load_jsonl("groundedness.jsonl"), judge=args.judge
                )
            )
    return results, skipped


def _print_report(results: list[SuiteResult], skipped: list[str], verbose: bool) -> None:
    for result in results:
        ran = bool(result.metrics or result.cases)
        status = ("PASS" if result.passed else "FAIL") if ran else "SKIP"
        metric_str = "  ".join(f"{k}={v:.2f}" for k, v in result.metrics.items()) or "—"
        print(f"\n[{status}] {result.suite}   {metric_str}")
        if result.note:
            print(f"       note: {result.note}")
        if result.thresholds:
            floors = "  ".join(f"{k}>={v}" for k, v in result.thresholds.items())
            print(f"       thresholds: {floors}")
        show = result.cases if verbose else [c for c in result.cases if not c.passed]
        for case in show:
            mark = "✓" if case.passed else "✗"
            print(f"       {mark} {case.name}  —  {case.detail}")

    if skipped:
        print(f"\nskipped (no LLM_API_KEY): {', '.join(skipped)}")

    ran = [r for r in results if r.metrics or r.cases]
    failed = [r.suite for r in ran if not r.passed]
    print("\n" + "=" * 60)
    if not ran:
        print("no suites ran (missing key and/or empty index)")
    elif failed:
        print(f"OVERALL: FAIL  ({', '.join(failed)})")
    else:
        print(f"OVERALL: PASS  ({len(ran)} suite(s))")


def _to_dict(result: SuiteResult) -> dict:
    return {
        "suite": result.suite,
        "passed": result.passed,
        "metrics": result.metrics,
        "thresholds": result.thresholds,
        "note": result.note,
        "cases": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.cases],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    parser.add_argument(
        "--suite", choices=[*ALL_SUITES, "all"], default="all", help="which suite to run"
    )
    parser.add_argument("--top-k", type=int, default=None, help="override RAG top_k for retrieval")
    parser.add_argument(
        "--judge", action="store_true", help="also compute an LLM-as-judge groundedness score"
    )
    parser.add_argument("--json", metavar="PATH", help="write a machine-readable report to PATH")
    parser.add_argument("-v", "--verbose", action="store_true", help="show passing cases too")
    args = parser.parse_args(argv)

    results, skipped = asyncio.run(_run(args))
    _print_report(results, skipped, args.verbose)

    if args.json:
        report = {"suites": [_to_dict(r) for r in results], "skipped": skipped}
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)

    ran = [r for r in results if r.metrics or r.cases]
    return 1 if any(not r.passed for r in ran) else 0


if __name__ == "__main__":
    sys.exit(main())
