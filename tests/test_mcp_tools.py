"""MCP tools tested over the real protocol (in-memory client <-> server)."""

import json

import httpx
import pytest
from mcp import Client

EXPECTED_TOOLS = {
    "search_knowledge_base",
    "get_employee",
    "list_employees",
    "get_time_off_balance",
    "get_public_holidays",
    "get_exchange_rate",
}


def parse(result) -> dict:
    return json.loads(result.content[0].text)


async def test_tool_discovery(mcp_server):
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == EXPECTED_TOOLS
        schema = next(t for t in tools.tools if t.name == "get_employee").input_schema
        assert schema["required"] == ["query"]


async def test_search_knowledge_base_returns_relevant_chunk(mcp_server):
    async with Client(mcp_server) as client:
        data = parse(
            await client.call_tool(
                "search_knowledge_base", {"query": "vacation paid time off PTO", "top_k": 1}
            )
        )
        assert data["results"][0]["source"] == "pto.md"
        assert "PTO" in data["results"][0]["text"]


async def test_employee_tools_roundtrip(mcp_server):
    async with Client(mcp_server) as client:
        employee = parse(await client.call_tool("get_employee", {"query": "2"}))
        assert employee["employee_number"] == 2
        assert "monthly_income" not in employee

        balance = parse(await client.call_tool("get_time_off_balance", {"employee": "2"}))
        assert balance["vacation_days_remaining"] >= 0

        missing = parse(await client.call_tool("get_employee", {"query": "Nobody Xyz"}))
        assert "error" in missing


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


class _FakeAsyncClient:
    responses: dict[str, _FakeResponse] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str):
        for fragment, response in self.responses.items():
            if fragment in url:
                return response
        return _FakeResponse(500, {})


@pytest.fixture
def fake_http(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


async def test_public_holidays_tool(mcp_server, fake_http):
    fake_http.responses = {
        "/PublicHolidays/2026/UA": _FakeResponse(
            200,
            [{"date": "2026-01-01", "name": "New Year's Day", "localName": "Новий рік"}],
        )
    }
    async with Client(mcp_server) as client:
        data = parse(
            await client.call_tool("get_public_holidays", {"country_code": "ua", "year": 2026})
        )
        assert data["country"] == "UA"
        assert data["holidays"][0]["name"] == "New Year's Day"


async def test_exchange_rate_tool_and_error_paths(mcp_server, fake_http):
    fake_http.responses = {
        "/latest/USD": _FakeResponse(
            200,
            {"result": "success", "rates": {"UAH": 41.5}, "time_last_update_utc": "today"},
        )
    }
    async with Client(mcp_server) as client:
        data = parse(await client.call_tool("get_exchange_rate", {"base": "usd", "target": "uah"}))
        assert data["rate"] == 41.5

        unknown = parse(
            await client.call_tool("get_exchange_rate", {"base": "usd", "target": "XXX"})
        )
        assert "error" in unknown

        fake_http.responses = {}  # every call now 500s -> tool reports, not raises
        failed = parse(await client.call_tool("get_public_holidays", {"country_code": "US"}))
        assert "error" in failed
