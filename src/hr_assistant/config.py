"""Application configuration.

Every setting is overridable via environment variables (or a local `.env` file),
so the same image runs unchanged on a laptop, in docker-compose and on Cloud Run.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app ---
    app_name: str = "HR Assistant"
    env: str = "dev"
    port: int = 8080
    log_level: str = "INFO"

    # --- LLM provider (OpenAI-compatible; defaults target Groq's free tier) ---
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""  # set GROQ key here; empty => live LLM calls disabled
    llm_model: str = "llama-3.3-70b-versatile"  # specialist agents
    router_model: str = "llama-3.1-8b-instant"  # cheap/fast intent router
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024

    # --- agents ---
    max_agent_iterations: int = 5
    memory_max_turns: int = 10  # conversation turns kept per session

    # --- data / storage ---
    docs_dir: Path = PROJECT_ROOT / "data" / "docs"
    db_path: Path = PROJECT_ROOT / "storage" / "hr.db"
    chroma_dir: Path = PROJECT_ROOT / "storage" / "chroma"
    rag_collection: str = "hr_handbook"
    rag_top_k: int = 4

    # --- MCP ---
    # URL the agents connect to; by default the server we host ourselves.
    mcp_url: str = ""  # empty => http://127.0.0.1:{port}/mcp at runtime

    # --- security ---
    app_api_key: str = ""  # empty => auth disabled (local dev)
    rate_limit_per_minute: int = 20
    max_message_chars: int = 2000

    # --- external APIs ---
    holidays_api_base: str = "https://date.nager.at/api/v3"
    exchange_api_base: str = "https://open.er-api.com/v6"
    external_api_timeout: float = 10.0

    @property
    def effective_mcp_url(self) -> str:
        return self.mcp_url or f"http://127.0.0.1:{self.port}/mcp"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
