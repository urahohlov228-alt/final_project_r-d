"""Thin LLM-provider abstraction.

Any OpenAI-compatible chat-completions endpoint works: Groq (default), OpenAI,
Ollama, vLLM... — switch providers via LLM_BASE_URL/LLM_API_KEY/LLM_MODEL env
vars, no code changes. Tests inject a fake client with the same interface.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI

from ..config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_message: dict = field(default_factory=dict)  # ready to append to history
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatLLM(Protocol):
    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


class OpenAICompatibleLLM:
    """Real client for any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, settings: Settings):
        self._client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-configured",
        )
        self._default_temperature = settings.llm_temperature
        self._default_max_tokens = settings.llm_max_tokens

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self._default_temperature if temperature is None else temperature,
            "max_tokens": self._default_max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        completion = await self._client.chat.completions.create(**kwargs)

        message = completion.choices[0].message
        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))

        usage = completion.usage
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            raw_message=message.model_dump(exclude_none=True),
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )
