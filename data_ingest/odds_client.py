"""OddsPapi client — fetches Pinnacle odds for all esports titles."""

import logging
import time
from typing import Any

import requests

from config import ODDSPAPI_API_KEY, ODDSPAPI_BASE, ODDSPAPI_SPORT_IDS, TOURNAMENT_CACHE_TTL

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# Retry delays for 429 responses (exponential backoff)
RETRY_DELAYS = [30, 60, 120]


class OddsClient:
    """Wraps the OddsPapi v4 API for retrieving sharp Pinnacle lines."""

    def __init__(self, api_key: str = ODDSPAPI_API_KEY) -> None:
        self.api_key = api_key
        self.session = requests.Session()
        # In-memory tournament cache: {sport_id: (timestamp, data)}
        self._tournament_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{ODDSPAPI_BASE}{path}"
        params = params or {}
        params["apiKey"] = self.api_key

        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 404:
                    return []
                if resp.status_code == 429:
                    if attempt < len(RETRY_DELAYS):
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "Rate limited (429) on %s — retrying in %ds (attempt %d/%d)",
                            path, delay, attempt + 1, len(RETRY_DELAYS),
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.error("Rate limited (429) on %s — all retries exhausted", path)
                        return None
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                logger.exception("OddsPapi request failed: %s", path)
                return None
        return None

    def get_tournaments(self, sport_id: int) -> list[dict[str, Any]]:
        """List active tournaments for a sport, with in-memory cache.

        Args:
            sport_id: OddsPapi numeric sport ID (e.g. 17 for CS2).
        """
        now = time.time()
        cached = self._tournament_cache.get(sport_id)
        if cached is not None:
            cached_at, cached_data = cached
            if now - cached_at < TOURNAMENT_CACHE_TTL:
                logger.debug("Using cached tournaments for sport_id=%d (age=%.0fs)", sport_id, now - cached_at)
                return cached_data

        data = self._get("/tournaments", params={"sportId": sport_id})
        result = data if isinstance(data, list) else []
        self._tournament_cache[sport_id] = (now, result)
        return result

    # OddsPapi allows max 5 tournament IDs per request
    BATCH_SIZE = 5

    def get_pinnacle_odds(
        self,
        tournament_ids: list[int | str],
        odds_format: str = "decimal",
    ) -> list[dict[str, Any]]:
        """Fetch Pinnacle odds for the given tournaments.

        Automatically batches large lists to stay within API URL limits.

        Args:
            tournament_ids: List of tournament IDs to query.
            odds_format: 'decimal' or 'american'.
        """
        if not tournament_ids:
            return []

        all_odds: list[dict[str, Any]] = []
        for i in range(0, len(tournament_ids), self.BATCH_SIZE):
            batch = tournament_ids[i : i + self.BATCH_SIZE]
            ids_str = ",".join(str(t) for t in batch)
            data = self._get(
                "/odds-by-tournaments",
                params={
                    "bookmaker": "pinnacle",
                    "tournamentIds": ids_str,
                    "oddsFormat": odds_format,
                },
            )
            if isinstance(data, list):
                all_odds.extend(data)
            # Courtesy delay between batches to avoid rate limits
            if i + self.BATCH_SIZE < len(tournament_ids):
                time.sleep(2)
        return all_odds

    def get_all_esports_odds(self) -> dict[str, list[dict[str, Any]]]:
        """Convenience method: fetch Pinnacle odds across every esport title.

        Returns a dict keyed by game name (cs2, lol, …) with the odds list
        as value.  Only queries tournaments that have upcoming or live
        fixtures to avoid 400 errors from the API.
        """
        results: dict[str, list[dict[str, Any]]] = {}

        for game, sport_id in ODDSPAPI_SPORT_IDS.items():
            tournaments = self.get_tournaments(sport_id)
            if not tournaments:
                logger.info("No active tournaments for %s (sport_id=%d)", game, sport_id)
                results[game] = []
                time.sleep(2)  # Rate-limit courtesy delay
                continue

            # Only keep tournaments with upcoming or live fixtures
            active_tournaments = [
                t for t in tournaments
                if (t.get("upcomingFixtures", 0) or 0) > 0
                or (t.get("liveFixtures", 0) or 0) > 0
            ]

            tournament_ids = [
                t.get("tournamentId") or t.get("id")
                for t in active_tournaments
            ]
            tournament_ids = [t for t in tournament_ids if t is not None]

            if not tournament_ids:
                logger.info(
                    "No active fixtures for %s (%d tournaments, 0 with upcoming/live)",
                    game, len(tournaments),
                )
                results[game] = []
                time.sleep(2)
                continue

            time.sleep(2)  # Rate-limit courtesy delay
            odds = self.get_pinnacle_odds(tournament_ids)
            results[game] = odds
            logger.info(
                "Fetched %d Pinnacle odds for %s across %d active tournaments (of %d total)",
                len(odds), game, len(tournament_ids), len(tournaments),
            )

        return results
