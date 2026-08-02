"""API tests over ASGI — no real network, LLM scripted, MCP in-memory."""

import httpx

from conftest import FakeLLM
from hr_assistant.agents import MCPToolbox
from hr_assistant.agents.llm import LLMResponse
from hr_assistant.api import create_app


def api_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health_and_config(settings, seeded_db, fake_store, mcp_server):
    app = create_app(settings, llm=FakeLLM([]), toolbox=MCPToolbox(mcp_server))
    async with app.router.lifespan_context(app), api_client(app) as client:
        health = (await client.get("/health")).json()
        assert health["checks"]["employees"] == 1233
        assert health["checks"]["llm_configured"] is True

        config = (await client.get("/api/config")).json()
        assert config["auth_required"] is False

        metrics = (await client.get("/metrics")).json()
        assert metrics["chat"]["total"] == 0


async def test_chat_happy_path(settings, seeded_db, fake_store, mcp_server):
    fake = FakeLLM(
        [
            LLMResponse(content='{"route": "off_topic", "reason": "smalltalk"}'),
        ]
    )
    app = create_app(settings, llm=fake, toolbox=MCPToolbox(mcp_server))
    async with app.router.lifespan_context(app), api_client(app) as client:
        response = await client.post("/api/chat", json={"message": "hi there"})
        assert response.status_code == 200
        body = response.json()
        assert body["route"] == "off_topic"
        assert body["session_id"]

        metrics = (await client.get("/metrics")).json()
        assert metrics["chat"]["total"] == 1
        assert metrics["chat"]["by_route"] == {"off_topic": 1}


async def test_auth_required(settings, seeded_db, fake_store, mcp_server):
    settings.app_api_key = "sekret"
    fake = FakeLLM([LLMResponse(content='{"route": "off_topic", "reason": "x"}')])
    app = create_app(settings, llm=fake, toolbox=MCPToolbox(mcp_server))
    async with app.router.lifespan_context(app), api_client(app) as client:
        assert (await client.post("/api/chat", json={"message": "hi"})).status_code == 401
        wrong = await client.post(
            "/api/chat", json={"message": "hi"}, headers={"X-API-Key": "nope"}
        )
        assert wrong.status_code == 401
        ok = await client.post(
            "/api/chat", json={"message": "hi"}, headers={"X-API-Key": "sekret"}
        )
        assert ok.status_code == 200


async def test_rate_limit(settings, seeded_db, fake_store, mcp_server):
    settings.rate_limit_per_minute = 2
    fake = FakeLLM(
        [
            LLMResponse(content='{"route": "off_topic", "reason": "1"}'),
            LLMResponse(content='{"route": "off_topic", "reason": "2"}'),
        ]
    )
    app = create_app(settings, llm=fake, toolbox=MCPToolbox(mcp_server))
    async with app.router.lifespan_context(app), api_client(app) as client:
        assert (await client.post("/api/chat", json={"message": "1"})).status_code == 200
        assert (await client.post("/api/chat", json={"message": "2"})).status_code == 200
        limited = await client.post("/api/chat", json={"message": "3"})
        assert limited.status_code == 429


async def test_llm_not_configured_returns_503(settings, seeded_db, fake_store, mcp_server):
    settings.llm_api_key = ""
    app = create_app(settings, llm=FakeLLM([]), toolbox=MCPToolbox(mcp_server))
    async with app.router.lifespan_context(app), api_client(app) as client:
        response = await client.post("/api/chat", json={"message": "hi"})
        assert response.status_code == 503


async def test_validation_rejects_bad_payloads(settings, seeded_db, fake_store, mcp_server):
    app = create_app(settings, llm=FakeLLM([]), toolbox=MCPToolbox(mcp_server))
    async with app.router.lifespan_context(app), api_client(app) as client:
        assert (await client.post("/api/chat", json={})).status_code == 422
        assert (await client.post("/api/chat", json={"message": ""})).status_code == 422
        too_long = {"message": "x" * 5000}
        assert (await client.post("/api/chat", json=too_long)).status_code == 422
