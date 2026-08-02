"""FastAPI application: chat API + web UI + the mounted MCP server.

Single deployable unit. Route registration order matters: API routes and
static files first, the MCP streamable-HTTP app is mounted at the root last,
so it only receives requests nothing else claimed (i.e. /mcp).
"""

import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mcp.server.transport_security import TransportSecuritySettings

from ..agents import ConversationMemory, MCPToolbox, OpenAICompatibleLLM, Orchestrator
from ..config import PROJECT_ROOT, Settings, get_settings
from ..logging_setup import log_event, setup_logging
from ..mcp_server import build_mcp_server
from .metrics import Metrics
from .ratelimit import RateLimiter

logger = logging.getLogger(__name__)

STATIC_DIR = PROJECT_ROOT / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    reply: str
    route: str
    agent: str
    session_id: str
    blocked: bool
    sources: list[dict]
    tool_calls: list[dict]
    usage: dict
    elapsed_ms: int


def create_app(
    settings: Settings | None = None,
    llm=None,
    toolbox: MCPToolbox | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    mcp_server = build_mcp_server(settings)
    mcp_http_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    llm = llm or OpenAICompatibleLLM(settings)
    # Agents speak real MCP over HTTP to our own /mcp endpoint by default;
    # tests inject an in-memory toolbox instead.
    toolbox = toolbox or MCPToolbox(settings.effective_mcp_url)
    memory = ConversationMemory(max_turns=settings.memory_max_turns)
    orchestrator = Orchestrator(llm, toolbox, memory, settings)
    metrics = Metrics()
    limiter = RateLimiter(settings.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_server.session_manager.run():
            log_event(logger, "startup", app=settings.app_name, env=settings.env)
            yield

    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.state.metrics = metrics
    app.state.orchestrator = orchestrator

    # ------------------------------------------------------------- middleware
    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        metrics.requests_total += 1
        if request.url.path not in ("/health", "/favicon.ico") and not request.url.path.startswith(
            "/static"
        ):
            log_event(
                logger,
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        return response

    # ------------------------------------------------------------------ auth
    def require_api_key(request: Request) -> str:
        """API-key auth for the chat API. Disabled when APP_API_KEY is empty."""
        if not settings.app_api_key:
            return _client_id(request)
        provided = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(provided, settings.app_api_key):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
        return _client_id(request)

    def _client_id(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    # ---------------------------------------------------------------- routes
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health():
        checks: dict = {"llm_configured": settings.llm_enabled}
        try:
            from ..rag.store import VectorStore

            store = VectorStore(str(settings.chroma_dir), settings.rag_collection)
            checks["index_chunks"] = store.count()
        except Exception as exc:  # noqa: BLE001
            checks["index_chunks"] = f"error: {exc}"
        try:
            from ..db import EmployeeDB

            departments = EmployeeDB(settings.db_path).departments()
            checks["employees"] = sum(d["headcount"] for d in departments)
        except Exception as exc:  # noqa: BLE001
            checks["employees"] = f"error: {exc}"
        ok = settings.llm_enabled and isinstance(checks["index_chunks"], int)
        return {"status": "ok" if ok else "degraded", "version": app.version, "checks": checks}

    @app.get("/metrics")
    async def get_metrics():
        return metrics.snapshot()

    @app.get("/api/config")
    async def api_config():
        return {
            "app_name": settings.app_name,
            "auth_required": bool(settings.app_api_key),
            "llm_configured": settings.llm_enabled,
            "model": settings.llm_model,
            "router_model": settings.router_model,
        }

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, client_id: str = Depends(require_api_key)):
        if not limiter.allow(client_id):
            metrics.rate_limited_total += 1
            raise HTTPException(status_code=429, detail="rate limit exceeded, try again later")
        if not settings.llm_enabled:
            raise HTTPException(
                status_code=503,
                detail="LLM provider is not configured (set LLM_API_KEY)",
            )
        session_id = body.session_id or uuid.uuid4().hex
        try:
            result = await orchestrator.handle(body.message, session_id)
        except Exception:
            metrics.chat_errors_total += 1
            logger.exception("chat request failed")
            raise HTTPException(status_code=500, detail="internal error, please retry") from None
        metrics.record_chat(result)
        return ChatResponse(
            reply=result.reply,
            route=result.route,
            agent=result.agent,
            session_id=result.session_id,
            blocked=result.blocked,
            sources=result.sources,
            tool_calls=result.tool_calls,
            usage={
                "llm_calls": result.llm_calls,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            },
            elapsed_ms=result.elapsed_ms,
        )

    # Static assets + the MCP app (root mount goes last — it catches /mcp).
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/", mcp_http_app)

    return app
