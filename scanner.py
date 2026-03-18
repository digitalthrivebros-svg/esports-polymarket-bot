"""Module 1: Discover open esports markets on Polymarket via Gamma + CLOB APIs."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from config import GAMMA_API_BASE, CLOB_API_BASE

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# Gamma API tag_ids for each esports game (from /sports endpoint)
# These are the CORRECT way to query esports events — NOT the `tag` parameter.
GAME_TAG_IDS: dict[str, str] = {
    "cs2": "100780",
    "dota2": "102366",
    "lol": "65",
    "valorant": "101672",
    "mlbb": "102750",
    "overwatch": "102753",
    "codmw": "100230",
    "pubg": "102754",
    "r6siege": "102755",
    "rl": "102756",
    "wildrift": "102752",
    "sc2": "102758",
}

# Only scan the main esports titles by default
DEFAULT_GAMES = ["cs2", "dota2", "lol", "valorant"]

# Generic outcomes to exclude from team name extraction
_GENERIC_OUTCOMES = frozenset({"Yes", "No", "Over", "Under", "Odd", "Even"})


@dataclass
class MarketBook:
    """Order-book snapshot for a single token."""

    token_id: str
    bids: list[dict[str, Any]] = field(default_factory=list)
    asks: list[dict[str, Any]] = field(default_factory=list)
    best_bid: float = 0.0
    best_ask: float = 0.0
    midpoint: float = 0.0
    spread: float = 0.0
    bid_liquidity: float = 0.0
    ask_liquidity: float = 0.0


@dataclass
class EsportsMarket:
    """Represents a single Polymarket esports market/condition."""

    condition_id: str
    question: str = ""
    token_ids: dict[str, str] = field(default_factory=dict)  # outcome -> token_id
    teams: list[str] = field(default_factory=list)
    start_time: str = ""
    series_format: str = ""  # BO1 / BO3 / BO5
    tournament: str = ""
    game: str = ""  # cs2 / lol / dota2 / valorant
    books: dict[str, MarketBook] = field(default_factory=dict)  # token_id -> book


class PolymarketScanner:
    """Scans Polymarket for open esports markets and fetches order-book data."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Gamma API helpers
    # ------------------------------------------------------------------

    def _gamma_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{GAMMA_API_BASE}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            logger.exception("Gamma API request failed: %s", path)
            return None

    def get_sport_configs(self) -> list[dict[str, Any]]:
        """GET /sports — retrieve sport configurations."""
        data = self._gamma_get("/sports")
        return data if isinstance(data, list) else []

    def get_market_types(self) -> list[dict[str, Any]]:
        """GET /sports/market-types — available market type definitions."""
        data = self._gamma_get("/sports/market-types")
        return data if isinstance(data, list) else []

    def get_teams(self) -> list[dict[str, Any]]:
        """GET /sports/teams — team data across all esports."""
        data = self._gamma_get("/sports/teams")
        return data if isinstance(data, list) else []

    def get_events_by_tag_id(self, tag_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """GET /events filtered by tag_id — the correct way to fetch esports events."""
        params: dict[str, Any] = {
            "active": "true",
            "closed": "false",
            "limit": str(limit),
            "tag_id": tag_id,
        }
        data = self._gamma_get("/events", params=params)
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # CLOB API helpers
    # ------------------------------------------------------------------

    def _clob_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{CLOB_API_BASE}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            logger.exception("CLOB API request failed: %s", path)
            return None

    def get_market_book(self, token_id: str) -> MarketBook:
        """Fetch full order book for a token."""
        data = self._clob_get("/book", params={"token_id": token_id})
        book = MarketBook(token_id=token_id)
        if not data:
            return book

        book.bids = data.get("bids", [])
        book.asks = data.get("asks", [])

        if book.bids:
            book.best_bid = float(book.bids[0].get("price", 0))
            book.bid_liquidity = sum(float(b.get("size", 0)) for b in book.bids)
        if book.asks:
            book.best_ask = float(book.asks[0].get("price", 0))
            book.ask_liquidity = sum(float(a.get("size", 0)) for a in book.asks)

        if book.best_bid and book.best_ask:
            book.spread = book.best_ask - book.best_bid
            book.midpoint = (book.best_bid + book.best_ask) / 2

        return book

    def get_midpoint(self, token_id: str) -> float | None:
        """GET /midpoint for a token."""
        data = self._clob_get("/midpoint", params={"token_id": token_id})
        if data and "mid" in data:
            return float(data["mid"])
        return None

    def get_spread(self, token_id: str) -> dict[str, float] | None:
        """GET /spread for a token — returns {bid, ask, spread}."""
        data = self._clob_get("/spread", params={"token_id": token_id})
        if not data:
            return None
        return {
            "bid": float(data.get("bid", 0)),
            "ask": float(data.get("ask", 0)),
            "spread": float(data.get("spread", 0)),
        }

    # ------------------------------------------------------------------
    # High-level scanning
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_field(raw: Any) -> list:
        """Safely parse a JSON string field into a list."""
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @staticmethod
    def _is_resolved(prices: list) -> bool:
        """Check if a market is resolved (one outcome at ~1, other at ~0)."""
        if len(prices) != 2:
            return False
        try:
            p = sorted([float(x) for x in prices])
            return p[0] < 0.01 and p[1] > 0.99
        except (ValueError, TypeError):
            return False

    def _parse_market(self, event: dict[str, Any], market: dict[str, Any], game: str) -> EsportsMarket | None:
        """Convert a raw Gamma market dict into an EsportsMarket.

        The Gamma API returns markets with:
        - clobTokenIds: JSON string like '["tokenA...", "tokenB..."]'
        - outcomes: JSON string like '["Team A", "Team B"]'
        - outcomePrices: JSON string like '["0.65", "0.35"]'
        """
        condition_id = market.get("conditionId") or market.get("condition_id", "")
        if not condition_id:
            return None

        # Parse JSON string fields from Gamma API
        clob_token_ids = self._parse_json_field(market.get("clobTokenIds"))
        outcomes_list = self._parse_json_field(market.get("outcomes"))
        prices = self._parse_json_field(market.get("outcomePrices"))

        # Skip markets with no token IDs
        if not clob_token_ids:
            return None

        # Skip resolved markets
        if self._is_resolved(prices):
            return None

        # Build outcome -> token_id mapping
        tokens: dict[str, str] = {}
        for i, tid in enumerate(clob_token_ids):
            outcome = outcomes_list[i] if i < len(outcomes_list) else f"outcome_{i}"
            tokens[outcome] = tid

        # Extract team names (outcomes that aren't generic)
        teams = [o for o in outcomes_list if o not in _GENERIC_OUTCOMES]

        question = market.get("question", "")
        series_format = ""
        for tag in ("BO1", "BO3", "BO5"):
            if tag.lower() in question.lower():
                series_format = tag.upper()
                break

        return EsportsMarket(
            condition_id=condition_id,
            question=question,
            token_ids=tokens,
            teams=teams,
            start_time=event.get("startDate", ""),
            series_format=series_format,
            tournament=event.get("title", ""),
            game=game,
        )

    def _is_match_market(self, market: dict[str, Any]) -> bool:
        """Check if a market is a head-to-head match (not a futures/prop bet)."""
        outcomes = self._parse_json_field(market.get("outcomes"))
        # Match markets have exactly 2 non-generic outcomes (team names)
        if len(outcomes) != 2:
            return False
        return all(o not in _GENERIC_OUTCOMES for o in outcomes)

    def scan_all_esports(self, games: list[str] | None = None) -> list[EsportsMarket]:
        """Scan esports categories via tag_id and return enriched markets with order books.

        Uses the Gamma API tag_id parameter which correctly returns esports events,
        unlike the broken `tag` parameter which returns stale non-esports data.
        """
        if games is None:
            games = DEFAULT_GAMES

        all_markets: list[EsportsMarket] = []
        seen_conditions: set[str] = set()

        for game in games:
            tag_id = GAME_TAG_IDS.get(game)
            if not tag_id:
                logger.warning("No tag_id configured for game '%s' — skipping", game)
                continue

            logger.info("Scanning %s (tag_id=%s)…", game, tag_id)
            events = self.get_events_by_tag_id(tag_id)

            if not events:
                logger.info("No events found for %s", game)
                continue

            match_event_count = 0
            for event in events:
                markets = event.get("markets", [])
                event_has_match = False

                for mkt_data in markets:
                    # Only process head-to-head match markets (skip futures, props, odd/even)
                    if not self._is_match_market(mkt_data):
                        continue

                    parsed = self._parse_market(event, mkt_data, game)
                    if parsed is None:
                        continue

                    # Deduplicate
                    if parsed.condition_id in seen_conditions:
                        continue
                    seen_conditions.add(parsed.condition_id)

                    # Fetch order books for each token
                    for outcome, token_id in parsed.token_ids.items():
                        try:
                            book = self.get_market_book(token_id)
                            parsed.books[token_id] = book
                        except Exception:
                            logger.exception(
                                "Failed to fetch book for token %s", token_id
                            )

                    all_markets.append(parsed)
                    event_has_match = True

                if event_has_match:
                    match_event_count += 1

            logger.info(
                "%s: found %d events with %d tradeable match markets",
                game,
                match_event_count,
                sum(1 for m in all_markets if m.game == game),
            )

        logger.info("Discovered %d esports match markets total", len(all_markets))

        if not all_markets:
            logger.info(
                "No active esports match markets found — this is normal between "
                "tournaments or during off-hours. Bot will check again next cycle."
            )

        return all_markets
