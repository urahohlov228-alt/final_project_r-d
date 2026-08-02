"""Orchestrator: the full request pipeline.

    user message
      → input guardrails (deterministic, no LLM)
      → router agent (fast model, classification only)
      → off_topic? → canned refusal (no LLM)
      → specialist agent (strong model + its MCP tools, agentic loop)
      → output guardrails
      → conversation memory
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from ..config import Settings
from ..guardrails import check_input, sanitize_output
from ..logging_setup import log_event
from .llm import ChatLLM
from .loop import run_agent_loop
from .mcp_client import MCPToolbox
from .memory import ConversationMemory
from .prompts import BLOCKED_INPUT_REPLY, OFF_TOPIC_REPLY
from .router import route_message
from .specialists import SPECIALISTS

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    reply: str
    route: str
    agent: str  # display name of the agent that produced the reply
    session_id: str
    blocked: bool = False
    block_reason: str = ""
    sources: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0


def _extract_sources(tool_calls) -> list[dict]:
    """Pull cited fragments out of search_knowledge_base results for the UI."""
    sources: list[dict] = []
    seen: set[tuple] = set()
    for record in tool_calls:
        if record.tool != "search_knowledge_base":
            continue
        payload = record.result_json()
        if not isinstance(payload, dict):
            continue
        for hit in payload.get("results", []):
            key = (hit.get("source"), hit.get("section"))
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "source": hit.get("source", ""),
                    "title": hit.get("title", ""),
                    "section": hit.get("section", ""),
                    "score": hit.get("score", 0.0),
                    "snippet": (hit.get("text", "") or "")[:400],
                }
            )
    return sources


class Orchestrator:
    def __init__(
        self,
        llm: ChatLLM,
        toolbox: MCPToolbox,
        memory: ConversationMemory,
        settings: Settings,
    ):
        self._llm = llm
        self._toolbox = toolbox
        self._memory = memory
        self._settings = settings

    async def handle(self, message: str, session_id: str | None = None) -> ChatResult:
        started = time.monotonic()
        session_id = session_id or uuid.uuid4().hex

        # 1. Input guardrails — deterministic, before any model sees the text.
        verdict = check_input(message, self._settings.max_message_chars)
        if not verdict.allowed:
            log_event(logger, "input_blocked", session=session_id, reason=verdict.reason)
            return ChatResult(
                reply=BLOCKED_INPUT_REPLY,
                route="blocked",
                agent="Guardrails",
                session_id=session_id,
                blocked=True,
                block_reason=verdict.reason,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        history = self._memory.history(session_id)

        # 2. Routing — cheap fast model decides who handles the request.
        decision = await route_message(
            self._llm, self._settings.router_model, message, history
        )
        log_event(
            logger, "routed", session=session_id, route=decision.route, reason=decision.reason
        )

        # 3. Off-topic: deterministic refusal, no specialist, no tools.
        if decision.route == "off_topic":
            self._memory.append_turn(session_id, message, OFF_TOPIC_REPLY)
            return ChatResult(
                reply=OFF_TOPIC_REPLY,
                route="off_topic",
                agent="Router",
                session_id=session_id,
                prompt_tokens=decision.prompt_tokens,
                completion_tokens=decision.completion_tokens,
                llm_calls=1,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        # 4. Specialist agent with its own MCP toolset.
        specialist = SPECIALISTS[decision.route]
        async with self._toolbox.session() as mcp_session:
            run = await run_agent_loop(
                llm=self._llm,
                model=self._settings.llm_model,
                system_prompt=specialist.system_prompt,
                history=history,
                user_message=message,
                session=mcp_session,
                allowed_tools=set(specialist.allowed_tools),
                max_iterations=self._settings.max_agent_iterations,
            )

        # 5. Output guardrails.
        reply = sanitize_output(run.content or "I couldn't produce an answer, please try again.")

        # 6. Memory.
        self._memory.append_turn(session_id, message, reply)

        result = ChatResult(
            reply=reply,
            route=decision.route,
            agent=specialist.display_name,
            session_id=session_id,
            sources=_extract_sources(run.tool_calls),
            tool_calls=[
                {"tool": r.tool, "arguments": r.arguments} for r in run.tool_calls
            ],
            llm_calls=run.llm_calls + 1,  # + router call
            prompt_tokens=run.prompt_tokens + decision.prompt_tokens,
            completion_tokens=run.completion_tokens + decision.completion_tokens,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        log_event(
            logger,
            "chat_handled",
            session=session_id,
            route=result.route,
            llm_calls=result.llm_calls,
            tool_calls=len(result.tool_calls),
            tokens=result.prompt_tokens + result.completion_tokens,
            elapsed_ms=result.elapsed_ms,
        )
        return result


def _pretty(obj) -> str:  # debugging helper for manual runs
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
