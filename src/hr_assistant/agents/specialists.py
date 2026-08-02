"""Specialist agent registry.

Each specialist = a system prompt + the minimal set of MCP tools for its
domain (least privilege: the Knowledge agent physically cannot look up
employees, the Info agent cannot read the handbook, etc.).
"""

from dataclasses import dataclass

from .prompts import EMPLOYEE_PROMPT, INFO_PROMPT, KNOWLEDGE_PROMPT


@dataclass(frozen=True)
class Specialist:
    key: str
    display_name: str
    system_prompt: str
    allowed_tools: frozenset[str]


SPECIALISTS: dict[str, Specialist] = {
    "knowledge": Specialist(
        key="knowledge",
        display_name="Knowledge Agent",
        system_prompt=KNOWLEDGE_PROMPT,
        allowed_tools=frozenset({"search_knowledge_base"}),
    ),
    "employee": Specialist(
        key="employee",
        display_name="Employee Agent",
        system_prompt=EMPLOYEE_PROMPT,
        allowed_tools=frozenset({"get_employee", "list_employees", "get_time_off_balance"}),
    ),
    "info": Specialist(
        key="info",
        display_name="Info Agent",
        system_prompt=INFO_PROMPT,
        allowed_tools=frozenset({"get_public_holidays", "get_exchange_rate"}),
    ),
}
