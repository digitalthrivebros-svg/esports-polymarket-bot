"""League of Legends data via PandaScore API."""

import logging
from typing import Any

import requests

from config import PANDASCORE_API_KEY, PANDASCORE_BASE

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


class LoLClient:
    """Fetches LoL match schedules, team stats, and player stats from PandaScore."""

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
            logger.exception("PandaScore LoL request failed: %s", path)
            return None

    def get_upcoming_matches(self, per_page: int = 50) -> list[dict[str, Any]]:
        """Return upcoming LoL matches."""
        data = self._get("/lol/matches/upcoming", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_teams(self, per_page: int = 50) -> list[dict[str, Any]]:
        """Return LoL teams."""
        data = self._get("/lol/teams", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_players(self, per_page: int = 50) -> list[dict[str, Any]]:
        """Return LoL players."""
        data = self._get("/lol/players", params={"per_page": per_page})
        return data if isinstance(data, list) else []

    def get_team_stats(self, team_id: int | str) -> dict[str, Any] | None:
        """Return stats for a specific LoL team."""
        data = self._get(f"/lol/teams/{team_id}")
        return data if isinstance(data, dict) else None

    def get_player_stats(self, player_id: int | str) -> dict[str, Any] | None:
        """Return stats for a specific LoL player."""
        data = self._get(f"/lol/players/{player_id}")
        return data if isinstance(data, dict) else None
