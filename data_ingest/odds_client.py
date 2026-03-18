"""OddsPapi client — fetches Pinnacle odds for all esports titles."""

import logging
import time
from typing import Any

import requests

from config import ODDSPAPI_API_KEY, ODDSPAPI_BASE, ODDSPAPI_SPORT_IDS

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


class OddsClient:
    """Wraps the OddsPapi v4 API for retrieving sharp Pinnacle lines."""

    def __init__(self, api_key: str = ODDSPAPI_API_KEY) -> None:
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{ODDSPAPI_BASE}{path}"
        params = params or {}
        params["apiKey"] = self.api_key
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            logger.exception("OddsPapi request failed: %s", path)
            return None

    def get_tournaments(self, sport_id: int) -> list[dict[str, Any]]:
        """List active tournaments for a sport.

        Args:
            sport_id: OddsPapi numeric sport ID (e.g. 17 for CS2).
        """
        data = self._get("/tournaments", params={"sportId": sport_id})
        return data if isinstance(data, list) else []

    def get_pinnacle_odds(
        self,
        tournament_ids: list[int | str],
        odds_format: str = "decimal",
    ) -> list[dict[str, Any]]:
        """Fetch Pinnacle odds for the given tournaments.

        Args:
            tournament_ids: List of tournament IDs to query.
            odds_format: 'decimal' or 'american'.
        """
        if not tournament_ids:
            return []
        ids_str = ",".join(str(t) for t in tournament_ids)
        data = self._get(
            "/odds-by-tournaments",
            params={
                "bookmaker": "pinnacle",
                "tournamentIds": ids_str,
                "oddsFormat": odds_format,
            },
        )
        return data if isinstance(data, list) else []

    def get_all_esports_odds(self) -> dict[str, list[dict[str, Any]]]:
        """Convenience method: fetch Pinnacle odds across every esport title.

        Returns a dict keyed by game name (cs2, lol, …) with the odds list
        as value.
        """
        results: dict[str, list[dict[str, Any]]] = {}

        for game, sport_id in ODDSPAPI_SPORT_IDS.items():
            tournaments = self.get_tournaments(sport_id)
            if not tournaments:
                logger.info("No active tournaments for %s (sport_id=%d)", game, sport_id)
                results[game] = []
                time.sleep(2)  # Rate-limit courtesy delay
                continue

            tournament_ids = [t.get("id") or t.get("tournamentId") for t in tournaments]
            tournament_ids = [t for t in tournament_ids if t is not None]

            time.sleep(2)  # Rate-limit courtesy delay
            odds = self.get_pinnacle_odds(tournament_ids)
            results[game] = odds
            logger.info(
                "Fetched %d Pinnacle odds for %s across %d tournaments",
                len(odds), game, len(tournament_ids),
            )

        return results
