"""Valorant data from vlrdevapi + VLR.gg REST fallback."""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

VLR_REST_BASE = "https://vlrggapi.vercel.app"
REQUEST_TIMEOUT = 15


class ValorantClient:
    """Fetches Valorant match and team data from vlrdevapi and VLR.gg REST API."""

    def __init__(self) -> None:
        self._vlr: Any = None
        self._rest_session = requests.Session()

    def _ensure_vlr(self) -> Any:
        if self._vlr is None:
            try:
                from vlrdevapi import vlr  # type: ignore[import-untyped]

                self._vlr = vlr
            except ImportError:
                logger.warning("vlrdevapi not installed — using REST fallback only")
        return self._vlr

    # ------------------------------------------------------------------
    # vlrdevapi wrapper
    # ------------------------------------------------------------------

    def get_upcoming_matches_vlr(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch upcoming matches via the vlrdevapi library."""
        vlr = self._ensure_vlr()
        if vlr is None:
            return self.get_upcoming_matches_rest()
        try:
            data = vlr.matches.upcoming(limit=limit)
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("vlrdevapi upcoming matches failed — trying REST")
            return self.get_upcoming_matches_rest()

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search for a team/player via vlrdevapi."""
        vlr = self._ensure_vlr()
        if vlr is None:
            return []
        try:
            data = vlr.search.search(query)
            return data if isinstance(data, list) else []
        except Exception:
            logger.exception("vlrdevapi search failed for '%s'", query)
            return []

    # ------------------------------------------------------------------
    # REST fallback (vlrggapi.vercel.app)
    # ------------------------------------------------------------------

    def _rest_get(self, path: str) -> Any:
        url = f"{VLR_REST_BASE}{path}"
        try:
            resp = self._rest_session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            logger.exception("VLR REST API request failed: %s", path)
            return None

    def get_upcoming_matches_rest(self) -> list[dict[str, Any]]:
        """Fetch upcoming matches via the VLR.gg REST API."""
        data = self._rest_get("/match/upcoming")
        if isinstance(data, dict):
            return data.get("data", [])
        return data if isinstance(data, list) else []

    def get_match_results(self) -> list[dict[str, Any]]:
        """Fetch recent match results via REST API."""
        data = self._rest_get("/match/results")
        if isinstance(data, dict):
            return data.get("data", [])
        return data if isinstance(data, list) else []

    def get_events(self) -> list[dict[str, Any]]:
        """Fetch current/upcoming events via REST API."""
        data = self._rest_get("/events")
        if isinstance(data, dict):
            return data.get("data", [])
        return data if isinstance(data, list) else []
