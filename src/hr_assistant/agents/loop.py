"""The agentic loop — deliberately transparent, no framework.

One iteration = one LLM call. If the model requests tools, we execute them via
MCP and feed results back; when it answers in plain text, we're done. A hard
iteration cap prevents runaway loops; when it's reached we force a final
text-only answer (tool_choice="none").
"""

import json
import logging
import time
from dataclasses import dataclass, field

from ..logging_setup import log_event
from .llm import ChatLLM
from .mcp_client import ToolboxSession

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    tool: str
    arguments: dict
    result: str  # JSON text as returned over MCP

    def result_json(self) -> dict | list | None:
        try:
            return json.loads(self.result)
        except (json.JSONDecodeError, TypeError):
            return None


@dataclass
class AgentRunResult:
    content: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: int = 0


async def run_agent_loop(
    llm: ChatLLM,
    model: str,
    system_prompt: str,
    history: list[dict],
    user_message: str,
    session: ToolboxSession,
    allowed_tools: set[str],
    max_iterations: int = 5,
) -> AgentRunResult:
    started = time.monotonic()
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]
    tools = await session.openai_tools(allowed_tools)
    run = AgentRunResult(content="")

    for iteration in range(max_iterations):
        forced_final = iteration == max_iterations - 1
        response = await llm.chat(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="none" if forced_final else "auto",
        )
        run.llm_calls += 1
        run.prompt_tokens += response.prompt_tokens
        run.completion_tokens += response.completion_tokens

        if not response.tool_calls:
            run.content = response.content or ""
            break

        messages.append(response.raw_message)
        for call in response.tool_calls:
            result_text = await session.call(call.name, call.arguments)
            log_event(
                logger,
                "tool_call",
                tool=call.name,
                arguments=call.arguments,
                result_chars=len(result_text),
                iteration=iteration,
            )
            run.tool_calls.append(
                ToolCallRecord(tool=call.name, arguments=call.arguments, result=result_text)
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result_text}
            )

    run.elapsed_ms = int((time.monotonic() - started) * 1000)
    return run
