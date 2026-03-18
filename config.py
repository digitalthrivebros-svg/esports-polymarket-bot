"""Configuration module — loads all settings from environment variables."""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Retrieve an environment variable, optionally raising if missing."""
    value = os.getenv(key, default)
    if required and not value:
        raise EnvironmentError(f"Required environment variable {key} is not set")
    return value  # type: ignore[return-value]


# --- API keys ---
POLYMARKET_PRIVATE_KEY: str = _get_env("POLYMARKET_PRIVATE_KEY", "")
ODDSPAPI_API_KEY: str = _get_env("ODDSPAPI_API_KEY", "")
PANDASCORE_API_KEY: str = _get_env("PANDASCORE_API_KEY", "")

# --- Risk parameters ---
RISK_MAX_POSITION_PER_MATCH: float = float(_get_env("RISK_MAX_POSITION_PER_MATCH", "100"))
RISK_MAX_TOTAL_EXPOSURE: float = float(_get_env("RISK_MAX_TOTAL_EXPOSURE", "500"))
RISK_MAX_DAILY_LOSS: float = float(_get_env("RISK_MAX_DAILY_LOSS", "50"))
RISK_MIN_EDGE_THRESHOLD: float = float(_get_env("RISK_MIN_EDGE_THRESHOLD", "0.03"))
RISK_MAX_MATCHES_CONCURRENT: int = int(_get_env("RISK_MAX_MATCHES_CONCURRENT", "10"))

# --- Execution ---
DRY_RUN: bool = _get_env("DRY_RUN", "true").lower() in ("true", "1", "yes")

# --- Paper trading ---
PAPER_BANKROLL: float = float(_get_env("PAPER_BANKROLL", "1000.0"))

# --- Scheduler ---
SCAN_INTERVAL_SECONDS: int = int(_get_env("SCAN_INTERVAL_SECONDS", "600"))

# --- Caching ---
TOURNAMENT_CACHE_TTL: int = int(_get_env("TOURNAMENT_CACHE_TTL", "3600"))

# --- Database ---
DB_PATH: str = _get_env("DB_PATH", "bot.db")

# --- Logging ---
LOG_LEVEL: str = _get_env("LOG_LEVEL", "INFO")

# --- Polymarket endpoints ---
GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"
CLOB_API_BASE: str = "https://clob.polymarket.com"
POLYGON_CHAIN_ID: int = 137

# --- OddsPapi ---
ODDSPAPI_BASE: str = "https://api.oddspapi.io/v4"
ODDSPAPI_SPORT_IDS: dict[str, int] = {
    "dota2": 16,
    "cs2": 17,
    "lol": 18,
    "valorant": 61,
    "honor_of_kings": 65,
}

# --- Gamma sport IDs ---
GAMMA_SPORT_IDS: dict[str, int] = {
    "csgo": 37,
    "dota2": 38,
    "lol": 39,
    "valorant": 40,
}

# --- PandaScore ---
PANDASCORE_BASE: str = "https://api.pandascore.co"


def configure_logging() -> None:
    """Set up root logger with a consistent format."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
