"""The three evaluation suites and their shared result types.

Each suite runs a golden set through one layer of the real system and reports
aggregate metrics plus per-case rows. Thresholds turn the numbers into a
pass/fail so `make eval` can gate a change.

Suite dependencies:
- routing       needs a live router LLM  (LLM_API_KEY)
- retrieval     needs a built vector index (`make data`), no LLM
- groundedness  needs both a live LLM and the built index + DB

The answer-assertion engine (`check_answer`) is pure and unit-tested offline.
"""

from dataclasses import dataclass, field

from . import metrics


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str


@dataclass
class SuiteResult:
    suite: str
    metrics: dict[str, float]
    cases: list[CaseResult]
    thresholds: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def passed(self) -> bool:
        if not self.thresholds:
            return all(c.passed for c in self.cases)
        return all(self.metrics.get(name, 0.0) >= floor for name, floor in self.thresholds.items())


# --------------------------------------------------------------- answer checks
_REFUSAL_MARKERS = (
    "can only help",
    "people team",
    "total rewards",
    "can't share",
    "cannot share",
    "can't process",
    "not able to",
    "outside my scope",
    "i'm the company's hr assistant",
    "couldn't find",
    "no employee found",
    "did you mean",
)


def check_answer(rec: dict, route: str, reply: str, has_sources: bool) -> tuple[bool, list[str]]:
    """Deterministic assertions for one end-to-end answer.

    Recognised keys on `rec`:
      expected_route, must_cite (bool), must_refuse (bool),
      must_include (list[str]), must_not_include (list[str]).
    Returns (passed, failure_reasons).
    """
    reasons: list[str] = []
    lower = reply.lower()

    expected_route = rec.get("expected_route")
    if expected_route and route != expected_route:
        reasons.append(f"route={route}, expected {expected_route}")

    if rec.get("must_cite") and not (has_sources or "[source:" in lower):
        reasons.append("no source citation")

    if rec.get("must_refuse") and not any(m in lower for m in _REFUSAL_MARKERS):
        reasons.append("expected a refusal/redirect")

    for needle in rec.get("must_include", []):
        if needle.lower() not in lower:
            reasons.append(f"missing {needle!r}")

    for needle in rec.get("must_not_include", []):
        if needle.lower() in lower:
            reasons.append(f"leaked {needle!r}")

    return (not reasons), reasons


# --------------------------------------------------------------------- suites
async def run_routing(llm, settings, dataset: list[dict]) -> SuiteResult:
    from hr_assistant.agents.router import route_message

    predictions, expected, cases = [], [], []
    for rec in dataset:
        decision = await route_message(
            llm, settings.router_model, rec["message"], rec.get("history", [])
        )
        exp = rec["expected_route"]
        predictions.append(decision.route)
        expected.append(exp)
        cases.append(
            CaseResult(
                name=rec["message"][:60],
                passed=decision.route == exp,
                detail=f"expected={exp} got={decision.route}",
            )
        )
    return SuiteResult(
        suite="routing",
        metrics={"accuracy": metrics.accuracy(predictions, expected)},
        cases=cases,
        thresholds={"accuracy": 0.85},
    )


def run_retrieval(settings, dataset: list[dict], top_k: int | None = None) -> SuiteResult:
    from hr_assistant.rag.store import VectorStore

    store = VectorStore(str(settings.chroma_dir), settings.rag_collection)
    if store.count() == 0:
        return SuiteResult(
            suite="retrieval",
            metrics={},
            cases=[],
            note="vector index is empty — run `make data` first",
        )

    k = top_k or settings.rag_top_k
    hits, rrs, cases = [], [], []
    for rec in dataset:
        retrieved = [hit["source"] for hit in store.search(rec["query"], top_k=k)]
        relevant = rec["expected_sources"]
        is_hit = metrics.hit_at_k(retrieved, relevant, k)
        hits.append(1.0 if is_hit else 0.0)
        rrs.append(metrics.reciprocal_rank(retrieved, relevant))
        cases.append(
            CaseResult(
                name=rec["query"][:60],
                passed=is_hit,
                detail=f"want one of {relevant}; got {retrieved[:k]}",
            )
        )
    return SuiteResult(
        suite="retrieval",
        metrics={f"hit@{k}": metrics.mean(hits), "mrr": metrics.mean(rrs)},
        cases=cases,
        thresholds={f"hit@{k}": 0.8},
    )


async def run_groundedness(llm, settings, dataset: list[dict], judge: bool = False) -> SuiteResult:
    from hr_assistant.agents import ConversationMemory, MCPToolbox, Orchestrator
    from hr_assistant.mcp_server import build_mcp_server

    orchestrator = Orchestrator(
        llm, MCPToolbox(build_mcp_server(settings)), ConversationMemory(), settings
    )

    passes, judged, cases = [], [], []
    for rec in dataset:
        result = await orchestrator.handle(rec["message"])
        ok, reasons = check_answer(
            rec, result.route, result.reply, has_sources=bool(result.sources)
        )
        passes.append(1.0 if ok else 0.0)
        detail = "ok" if ok else "; ".join(reasons)
        if judge and llm is not None:
            score = await _judge(llm, settings, rec["message"], result.reply, result.sources)
            if score is not None:
                judged.append(score)
                detail = f"{detail} | judge={score}/5"
        cases.append(CaseResult(name=rec["message"][:60], passed=ok, detail=detail))

    suite_metrics = {"pass_rate": metrics.mean(passes)}
    if judged:
        suite_metrics["avg_judge"] = metrics.mean(judged)  # reported, not gated
    return SuiteResult(
        suite="groundedness",
        metrics=suite_metrics,
        cases=cases,
        thresholds={"pass_rate": 0.9},
    )


async def _judge(llm, settings, question: str, reply: str, sources: list[dict]) -> float | None:
    """Optional LLM-as-judge: 1-5 groundedness score. Non-gating, best-effort."""
    import json
    import re

    context = "\n".join(f"- {s.get('snippet', '')}" for s in sources) or "(no sources retrieved)"
    prompt = (
        "You grade an HR assistant's answer for groundedness. Given the question, "
        "the retrieved sources and the answer, score 1-5 how well the answer is "
        "supported by the sources and actually addresses the question (5 = fully "
        "grounded and on-point, 1 = unsupported or evasive). "
        'Reply with ONLY JSON: {"score": <int>}.\n\n'
        f"Question: {question}\n\nSources:\n{context}\n\nAnswer:\n{reply}"
    )
    try:
        response = await llm.chat(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=20,
        )
        match = re.search(r"\{.*\}", response.content or "", re.DOTALL)
        if match:
            return float(json.loads(match.group(0))["score"])
    except (ValueError, KeyError, TypeError):
        return None
    return None
