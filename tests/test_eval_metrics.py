"""Offline unit tests for the eval harness machinery.

Covers the pure metric functions, the answer-assertion engine and dataset
loading — everything that must keep working without an LLM key or a built
index, so the harness itself can't silently rot.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals import data, metrics  # noqa: E402
from evals.suites import check_answer  # noqa: E402


def test_accuracy_and_confusion():
    predictions = ["knowledge", "employee", "info", "off_topic"]
    expected = ["knowledge", "employee", "info", "knowledge"]
    assert metrics.accuracy(predictions, expected) == pytest.approx(0.75)
    counts = metrics.confusion_counts(predictions, expected)
    assert counts[("knowledge", "off_topic")] == 1
    assert counts[("employee", "employee")] == 1


def test_accuracy_empty_is_zero():
    assert metrics.accuracy([], []) == 0.0


def test_hit_and_reciprocal_rank():
    retrieved = ["a.md", "b.md", "c.md"]
    assert metrics.hit_at_k(retrieved, ["c.md"], k=3) is True
    assert metrics.hit_at_k(retrieved, ["c.md"], k=2) is False
    assert metrics.reciprocal_rank(retrieved, ["b.md"]) == pytest.approx(0.5)
    assert metrics.reciprocal_rank(retrieved, ["zzz.md"]) == 0.0


def test_recall_at_k():
    retrieved = ["a.md", "b.md", "c.md"]
    assert metrics.recall_at_k(retrieved, ["a.md", "c.md"], k=3) == pytest.approx(1.0)
    assert metrics.recall_at_k(retrieved, ["a.md", "zzz.md"], k=3) == pytest.approx(0.5)
    assert metrics.recall_at_k(retrieved, [], k=3) == 0.0


def test_mean():
    assert metrics.mean([1.0, 0.0, 0.5]) == pytest.approx(0.5)
    assert metrics.mean([]) == 0.0


def test_check_answer_route_and_citation():
    rec = {"expected_route": "knowledge", "must_cite": True}
    reply = "PTO is flexible. [source: time-off.md — PTO]"
    ok, reasons = check_answer(rec, "knowledge", reply, False)
    assert ok and reasons == []

    ok, reasons = check_answer(rec, "employee", "PTO is flexible.", False)
    assert not ok
    assert any("route" in r for r in reasons)
    assert any("citation" in r for r in reasons)


def test_check_answer_citation_via_sources_flag():
    rec = {"must_cite": True}
    ok, _ = check_answer(rec, "knowledge", "Here is the policy.", has_sources=True)
    assert ok


def test_check_answer_refusal_and_leak():
    rec = {"must_refuse": True, "must_not_include": ["$"]}
    refusal = "I can't share that — please contact the People team."
    ok, _ = check_answer(rec, "employee", refusal, False)
    assert ok

    ok, reasons = check_answer(rec, "employee", "Her salary is $95000.", False)
    assert not ok
    assert any("refusal" in r for r in reasons)
    assert any("leaked" in r for r in reasons)


def test_check_answer_must_include():
    rec = {"must_include": ["Ukraine"]}
    assert check_answer(rec, "info", "Holidays in Ukraine for 2026...", False)[0]
    assert not check_answer(rec, "info", "Holidays for 2026...", False)[0]


def test_datasets_load_and_are_well_formed():
    routing = data.load_jsonl("routing.jsonl")
    retrieval = data.load_jsonl("retrieval.jsonl")
    groundedness = data.load_jsonl("groundedness.jsonl")

    assert routing and all("message" in r and "expected_route" in r for r in routing)
    valid_routes = {"knowledge", "employee", "info", "off_topic"}
    assert {r["expected_route"] for r in routing} <= valid_routes

    assert retrieval and all(r.get("expected_sources") for r in retrieval)
    assert all(isinstance(r["expected_sources"], list) for r in retrieval)

    assert groundedness and all("message" in r for r in groundedness)
