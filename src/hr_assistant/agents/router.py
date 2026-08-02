"""Intent router — the first stage of every request.

A small fast model (llama-3.1-8b on Groq) classifies the message into one of
four routes; the orchestrator then dispatches to the matching specialist. The
router never sees any tools — classification only, so it is cheap and its
output space is closed (guardrail by construction: unknown labels fall back
to the most general route).
"""

import json
import logging
import re
from dataclasses import dataclass

from .llm import ChatLLM
from .prompts import ROUTER_PROMPT

logger = logging.getLogger(__name__)

ROUTES = ("knowledge", "employee", "info", "off_topic")
DEFAULT_ROUTE = "knowledge"

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class RouteDecision:
    route: str
    reason: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _context_block(history: list[dict], max_turns: int = 3) -> str:
    """Compress the last few turns so follow-up questions route correctly."""
    recent = [m for m in history if m.get("role") in ("user", "assistant")][-max_turns * 2 :]
    if not recent:
        return ""
    lines = [f"{m['role']}: {str(m.get('content', ''))[:200]}" for m in recent]
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


def parse_route(raw: str | None) -> RouteDecision:
    """Parse the router model's reply; anything unparseable → default route."""
    if raw:
        match = _JSON_RE.search(raw)
        if match:
            try:
                data = json.loads(match.group(0))
                route = str(data.get("route", "")).strip().lower()
                if route in ROUTES:
                    return RouteDecision(route=route, reason=str(data.get("reason", "")))
            except json.JSONDecodeError:
                pass
    logger.warning("router returned unparseable output: %.120s", raw)
    return RouteDecision(route=DEFAULT_ROUTE, reason="fallback: unparseable router output")


async def route_message(
    llm: ChatLLM, model: str, message: str, history: list[dict]
) -> RouteDecision:
    user_block = f"{_context_block(history)}User: {message}"
    response = await llm.chat(
        model=model,
        messages=[
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": user_block},
        ],
        temperature=0.0,
        max_tokens=120,
    )
    decision = parse_route(response.content)
    decision.prompt_tokens = response.prompt_tokens
    decision.completion_tokens = response.completion_tokens
    return decision
