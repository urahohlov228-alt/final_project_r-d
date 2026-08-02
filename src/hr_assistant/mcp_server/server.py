"""The MCP server: every data source the agents can touch lives behind these tools.

Exposed over two transports from the same code:
- streamable HTTP (`/mcp`) — used by our own agents and any remote MCP client;
- stdio (`python -m hr_assistant.mcp_server`) — used by Claude Desktop & co.

Tools return plain dicts (MCP structured content). Errors are returned as
`{"error": ...}` values instead of raised exceptions, so the calling LLM can
read what went wrong and recover (ask the user, retry with other arguments).
"""

import datetime
import logging

import httpx

from mcp.server import MCPServer

from ..config import Settings, get_settings
from ..db import EmployeeDB
from ..rag.store import VectorStore

logger = logging.getLogger(__name__)

_stores: dict[str, VectorStore] = {}


def _store(settings: Settings) -> VectorStore:
    """One VectorStore (and thus one Chroma client) per persist directory."""
    key = str(settings.chroma_dir)
    if key not in _stores:
        _stores[key] = VectorStore(key, settings.rag_collection)
    return _stores[key]


def _db(settings: Settings) -> EmployeeDB:
    return EmployeeDB(settings.db_path)


def build_mcp_server(settings: Settings | None = None) -> MCPServer:
    settings = settings or get_settings()

    server = MCPServer(
        name="hr-assistant",
        instructions=(
            "Tools for an HR assistant: semantic search over the company handbook, "
            "employee directory lookups, time-off balances, public holidays and "
            "currency exchange rates."
        ),
    )

    # ------------------------------------------------------------------ RAG
    @server.tool()
    def search_knowledge_base(query: str, top_k: int = 0) -> dict:
        """Semantic search over the company handbook (HR policies: time off, PTO,
        benefits, onboarding, remote work, expenses, code of conduct).

        Args:
            query: A natural-language question or phrase to search for.
            top_k: How many text fragments to return (default from server config).
        """
        k = top_k if 0 < top_k <= 10 else settings.rag_top_k
        try:
            hits = _store(settings).search(query, top_k=k)
        except Exception as exc:  # index missing / not built yet
            logger.exception("knowledge base search failed")
            return {"error": f"knowledge base unavailable: {exc}"}
        return {"query": query, "results": hits}

    # ----------------------------------------------------------- employee DB
    @server.tool()
    def get_employee(query: str) -> dict:
        """Look up a single employee by full/partial name, e-mail, or employee number.

        Returns the employee's profile (department, role, tenure). Salary and other
        sensitive compensation data are intentionally not available.
        """
        employee = _db(settings).find_employee(query)
        if employee is None:
            suggestions = _db(settings).suggest_names(query)
            return {"error": f"no employee found for '{query}'", "suggestions": suggestions}
        return employee

    @server.tool()
    def list_employees(department: str = "", job_role: str = "", limit: int = 10) -> dict:
        """List employees, optionally filtered by department and/or job role.

        Departments: 'Human Resources', 'Research & Development', 'Sales'.
        With no filters, returns department headcounts instead of people.
        """
        db = _db(settings)
        if not department and not job_role:
            return {"departments": db.departments()}
        return db.list_employees(department, job_role, limit)

    @server.tool()
    def get_time_off_balance(employee: str) -> dict:
        """Get vacation/sick day balances for an employee (by name, e-mail or number)."""
        balance = _db(settings).get_time_off(employee)
        if balance is None:
            suggestions = _db(settings).suggest_names(employee)
            return {"error": f"no employee found for '{employee}'", "suggestions": suggestions}
        return balance

    # ---------------------------------------------------------- external APIs
    @server.tool()
    async def get_public_holidays(country_code: str = "US", year: int = 0) -> dict:
        """Public holidays for a country (ISO 3166-1 alpha-2 code, e.g. US, UA, DE, PL).

        Args:
            country_code: Two-letter country code.
            year: Calendar year; 0 means the current year.
        """
        year = year or datetime.date.today().year
        url = f"{settings.holidays_api_base}/PublicHolidays/{year}/{country_code.upper()}"
        try:
            async with httpx.AsyncClient(timeout=settings.external_api_timeout) as client:
                response = await client.get(url)
            if response.status_code == 404:
                return {"error": f"unknown country code '{country_code}'"}
            response.raise_for_status()
            holidays = [
                {"date": h["date"], "name": h["name"], "local_name": h["localName"]}
                for h in response.json()
            ]
            return {"country": country_code.upper(), "year": year, "holidays": holidays}
        except httpx.HTTPError as exc:
            return {"error": f"holidays API unavailable: {exc}"}

    @server.tool()
    async def get_exchange_rate(base: str = "USD", target: str = "UAH") -> dict:
        """Current currency exchange rate (ISO 4217 codes, e.g. USD, EUR, UAH, PLN)."""
        url = f"{settings.exchange_api_base}/latest/{base.upper()}"
        try:
            async with httpx.AsyncClient(timeout=settings.external_api_timeout) as client:
                response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if data.get("result") != "success":
                return {"error": f"exchange API error: {data.get('error-type', 'unknown')}"}
            rate = data["rates"].get(target.upper())
            if rate is None:
                return {"error": f"unknown currency '{target}'"}
            return {
                "base": base.upper(),
                "target": target.upper(),
                "rate": rate,
                "updated": data.get("time_last_update_utc", ""),
            }
        except httpx.HTTPError as exc:
            return {"error": f"exchange rate API unavailable: {exc}"}

    return server
