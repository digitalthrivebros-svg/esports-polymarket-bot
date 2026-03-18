"""CS2 data from HLTV via hltv-async-api."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class HLTVClient:
    """Async wrapper around the hltv-async-api library for CS2 data.

    Provides team rankings, upcoming matches, match details, and team info.
    """

    def __init__(self) -> None:
        self._hltv: Any = None

    def _ensure_client(self) -> Any:
        if self._hltv is None:
            try:
                from hltv_async_api import Hltv  # type: ignore[import-untyped]

                self._hltv = Hltv()
            except ImportError:
                raise RuntimeError(
                    "hltv-async-api is not installed. Run: pip install hltv-async-api"
                )
        return self._hltv

    async def get_top_teams(self, max_teams: int = 100) -> list[dict[str, Any]]:
        """Fetch current HLTV team rankings.

        Returns a list of dicts with team name, rank, and points.
        """
        hltv = self._ensure_client()
        try:
            teams = await hltv.get_top_teams(max_teams=max_teams)
            logger.info("Fetched %d top CS2 teams from HLTV", len(teams) if teams else 0)
            return teams if isinstance(teams, list) else []
        except Exception:
            logger.exception("Failed to fetch HLTV top teams")
            return []

    async def get_upcoming_matches(self, days: int = 7) -> list[dict[str, Any]]:
        """Fetch upcoming CS2 matches within the next *days* days."""
        hltv = self._ensure_client()
        try:
            matches = await hltv.get_upcoming_matches(days=days)
            logger.info("Fetched %d upcoming CS2 matches", len(matches) if matches else 0)
            return matches if isinstance(matches, list) else []
        except Exception:
            logger.exception("Failed to fetch HLTV upcoming matches")
            return []

    async def get_match_info(self, match_id: int | str) -> dict[str, Any] | None:
        """Fetch detailed information for a specific match."""
        hltv = self._ensure_client()
        try:
            info = await hltv.get_match_info(match_id)
            return info if isinstance(info, dict) else None
        except Exception:
            logger.exception("Failed to fetch HLTV match info for %s", match_id)
            return None

    async def get_team_info(self, team_id: int | str) -> dict[str, Any] | None:
        """Fetch team details: roster, recent results, map pool."""
        hltv = self._ensure_client()
        try:
            info = await hltv.get_team_info(team_id)
            return info if isinstance(info, dict) else None
        except Exception:
            logger.exception("Failed to fetch HLTV team info for %s", team_id)
            return None
