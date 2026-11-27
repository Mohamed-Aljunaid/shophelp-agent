"""App settings, read from environment variables and .env (see .env.example)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""

    llm_max_requests_per_minute: int = 10
    llm_max_retries: int = 5
    llm_cache: bool = True
    llm_cache_path: Path = ROOT / "data" / "llm_cache.sqlite"

    db_path: Path = ROOT / "data" / "shop.db"
    refund_approval_threshold: float = 200.0  # refunds above this need staff approval
    cors_origins: list[str] = ["http://localhost:5280"]  # the Vite dev server (frontend/vite.config.ts)
    staff_token: str = ""  # required in X-Staff-Token for POST /approvals; empty = approvals disabled

    eval_split: str = "test"      # tau3 split: test (40), train (74) or base (all 114)
    eval_task_count: int = 15     # first N tasks of the split
    eval_task_ids: str = ""       # comma-separated ids; overrides split and count
    eval_trials: int = 3


settings = Settings()
