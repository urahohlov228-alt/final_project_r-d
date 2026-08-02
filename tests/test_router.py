from conftest import FakeLLM
from hr_assistant.agents.llm import LLMResponse
from hr_assistant.agents.router import DEFAULT_ROUTE, parse_route, route_message


def test_parse_route_valid():
    decision = parse_route('{"route": "employee", "reason": "lookup"}')
    assert decision.route == "employee"
    assert decision.reason == "lookup"


def test_parse_route_json_with_noise():
    decision = parse_route('Sure! {"route": "info", "reason": "holidays"} hope that helps')
    assert decision.route == "info"


def test_parse_route_unknown_label_falls_back():
    assert parse_route('{"route": "hacker", "reason": "?"}').route == DEFAULT_ROUTE


def test_parse_route_garbage_falls_back():
    assert parse_route("no json here").route == DEFAULT_ROUTE
    assert parse_route(None).route == DEFAULT_ROUTE
    assert parse_route('{"broken": ').route == DEFAULT_ROUTE


async def test_route_message_uses_router_model_and_history():
    fake = FakeLLM([LLMResponse(content='{"route": "employee", "reason": "follow-up"}')])
    history = [
        {"role": "user", "content": "What team is Olivia Smith on?"},
        {"role": "assistant", "content": "R&D."},
    ]
    decision = await route_message(
        fake, "router-model", "How many days does she have left?", history
    )

    assert decision.route == "employee"
    call = fake.calls[0]
    assert call["model"] == "router-model"
    assert call["tools"] == []  # the router never sees tools
    user_block = call["messages"][1]["content"]
    assert "Olivia Smith" in user_block  # history included for follow-up context
