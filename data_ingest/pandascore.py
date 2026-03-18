"""PandaScore API wrapper — schedules, rosters, and stats across multiple esports."""

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from config import PANDASCORE_API_KEY, PANDASCORE_BASE

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# PandaScore game slugs used in URL paths
GAME_SLUGS = ("csgo", "lol", "dota2", "valorant")


class PandaScoreClient:
    """Generic PandaScore client covering LoL, CS2, Dota 2, and Valorant.

    Free tier allows 1 000 requests / hour.
    """

    def __init__(self, api_key: str = PANDASCORE_API_KEY) -> None:
        self.api_key = api_key
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{PANDASCORE_BASE}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            logger.exception("PandaScore request failed: %s", path)
            return None

    # ------------------------------------------------------------------
    # Per-game helpers
    # ------------------------------------------------------------------

    def get_upcoming_matches(self, game: str, per_page: int = 50) -> list[dict[str, Any]]:
        """Upcoming matches for a game (e.g. 'csgo', 'lol')."""
        data = self._get(f"/{game}/matches/upcoming", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_running_matches(self, game: str, per_page: int = 50) -> list[dict[str, Any]]:
        """Currently running matches."""
        data = self._get(f"/{game}/matches/running", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_teams(self, game: str, per_page: int = 50) -> list[dict[str, Any]]:
        """Teams for a given game."""
        data = self._get(f"/{game}/teams", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_team(self, game: str, team_id: int | str) -> dict[str, Any] | None:
        """Details for a specific team."""
        data = self._get(f"/{game}/teams/{team_id}")
        return data if isinstance(data, dict) else None

    def get_players(self, game: str, per_page: int = 50) -> list[dict[str, Any]]:
        """Players for a given game."""
        data = self._get(f"/{game}/players", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_tournaments(self, game: str, per_page: int = 50) -> list[dict[str, Any]]:
        """Active tournaments for a game."""
        data = self._get(f"/{game}/tournaments", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_past_matches(self, game: str, days_back: int = 3, per_page: int = 50) -> list[dict[str, Any]]:
        """Completed matches for a game within the last N days.

        Returns matches with ``winner`` object containing ``id`` and ``name``,
        plus ``opponents`` array.
        """
        end = datetime.utcnow()
        start = end - timedelta(days=days_back)
        params = {
            "per_page": per_page,
            "filter[status]": "finished",
            "range[end_at]": f"{start.strftime('%Y-%m-%dT00:00:00Z')},{end.strftime('%Y-%m-%dT23:59:59Z')}",
        }
        data = self._get(f"/{game}/matches/past", params=params)
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Cross-game convenience
    # ------------------------------------------------------------------

    def get_all_upcoming_matches(self) -> dict[str, list[dict[str, Any]]]:
        """Return upcoming matches for every supported game, keyed by slug."""
        results: dict[str, list[dict[str, Any]]] = {}
        for game in GAME_SLUGS:
            results[game] = self.get_upcoming_matches(game)
            logger.info("PandaScore: %d upcoming %s matches", len(results[game]), game)
        return results

    def get_all_past_matches(self, days_back: int = 3) -> dict[str, list[dict[str, Any]]]:
        """Return past matches for every supported game, keyed by slug."""
        results: dict[str, list[dict[str, Any]]] = {}
        for game in GAME_SLUGS:
            results[game] = self.get_past_matches(game, days_back=days_back)
            logger.info("PandaScore: %d past %s matches (last %d days)", len(results[game]), game, days_back)
        return results
