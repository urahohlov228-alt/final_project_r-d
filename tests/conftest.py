"""Shared fixtures.

Everything runs offline: no LLM key, no embedding-model download, no external
APIs. The LLM is scripted, embeddings are a deterministic bag-of-words hash,
external HTTP calls are stubbed.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chromadb.api.types import EmbeddingFunction  # noqa: E402

from hr_assistant.agents.llm import LLMResponse, ToolCall  # noqa: E402
from hr_assistant.config import PROJECT_ROOT, Settings  # noqa: E402
from hr_assistant.rag.chunking import Chunk  # noqa: E402
from hr_assistant.rag.store import VectorStore  # noqa: E402


class HashEmbeddings(EmbeddingFunction):
    """Deterministic bag-of-words embedding — word overlap => similarity.

    Implements Chroma's EmbeddingFunction interface so tests never download
    the real ONNX model.
    """

    DIM = 64

    def __init__(self):
        pass

    @staticmethod
    def name() -> str:
        return "hash_test_embeddings"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config):  # noqa: ARG004
        return HashEmbeddings()

    def __call__(self, input):  # chroma's expected signature
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for token in text.lower().split():
            token = token.strip(".,:;()[]#*-\"'")
            if not token:
                continue
            index = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.DIM
            vec[index] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


class FakeLLM:
    """Replays a scripted list of LLMResponse objects and records every call."""

    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self.calls: list[dict] = []

    async def chat(self, model, messages, tools=None, tool_choice=None,
                   temperature=None, max_tokens=None):
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": [t["function"]["name"] for t in (tools or [])],
                "tool_choice": tool_choice,
            }
        )
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        return self.script.pop(0)


def tool_call_response(name: str, arguments_json: str) -> LLMResponse:
    """An assistant turn that requests one tool call."""
    import json

    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name=name, arguments=json.loads(arguments_json))],
        raw_message={
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": name, "arguments": arguments_json},
                }
            ],
        },
        prompt_tokens=10,
        completion_tokens=5,
    )


SAMPLE_CHUNKS = [
    Chunk(
        id="pto.md#0",
        text="[Time Off — PTO]\nEmployees get flexible paid time off PTO vacation days "
        "with manager approval required for more than 25 consecutive days",
        source="pto.md",
        title="Time Off",
        section="PTO",
    ),
    Chunk(
        id="expenses.md#0",
        text="[Expenses — Reimbursement]\nCompany money spending reimbursement requires "
        "receipts submitted within 30 days through the expenses portal",
        source="expenses.md",
        title="Expenses",
        section="Reimbursement",
    ),
]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        llm_api_key="test-key",
        db_path=tmp_path / "hr.db",
        chroma_dir=tmp_path / "chroma",
        docs_dir=PROJECT_ROOT / "data" / "docs",
        rate_limit_per_minute=1000,
        _env_file=None,  # ignore any local .env
    )


@pytest.fixture
def seeded_db(settings):
    sys.path.insert(0, str(PROJECT_ROOT / "data"))
    from seed_db import seed

    seed(settings.db_path)
    return settings.db_path


@pytest.fixture
def fake_store(settings) -> VectorStore:
    store = VectorStore(str(settings.chroma_dir), settings.rag_collection, HashEmbeddings())
    store.rebuild(SAMPLE_CHUNKS)
    return store


@pytest.fixture
def mcp_server(settings, seeded_db, fake_store):
    """MCP server wired to the tmp DB and the fake-embedding store."""
    from hr_assistant.mcp_server import server as server_module

    server_module._stores[str(settings.chroma_dir)] = fake_store
    return server_module.build_mcp_server(settings)
