"""Module 1: Discover open esports markets on Polymarket via Gamma + CLOB APIs."""

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from config import GAMMA_API_BASE, CLOB_API_BASE, GAMMA_SPORT_IDS

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


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

    def get_events(self, sport_tag: str | None = None) -> list[dict[str, Any]]:
        """GET /events — optionally filtered by sport tag slug."""
        params: dict[str, Any] = {"active": "true"}
        if sport_tag:
            params["tag"] = sport_tag
        else:
            params["tag"] = "esports"
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

    def _parse_market(self, event: dict[str, Any], market: dict[str, Any], game: str) -> EsportsMarket | None:
        """Convert a raw Gamma market dict into an EsportsMarket."""
        condition_id = market.get("conditionId") or market.get("condition_id", "")
        if not condition_id:
            return None

        tokens: dict[str, str] = {}
        for token in market.get("tokens", []):
            outcome = token.get("outcome", "")
            tid = token.get("token_id", "")
            if outcome and tid:
                tokens[outcome] = tid

        teams: list[str] = []
        for token in market.get("tokens", []):
            outcome = token.get("outcome", "")
            if outcome and outcome not in ("Yes", "No", "Over", "Under"):
                teams.append(outcome)

        question = market.get("question", "")
        series_format = ""
        for tag in ("BO1", "BO3", "BO5", "Bo1", "Bo3", "Bo5", "bo1", "bo3", "bo5"):
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

    def scan_all_esports(self) -> list[EsportsMarket]:
        """Scan all esport categories and return enriched markets with order books."""
        all_markets: list[EsportsMarket] = []

        for game, sport_id in GAMMA_SPORT_IDS.items():
            logger.info("Scanning %s (sport_id=%d)…", game, sport_id)
            events = self.get_events(sport_tag=game)
            if not events:
                events = self.get_events(sport_tag="esports")

            for event in events:
                markets = event.get("markets", [])
                for mkt_data in markets:
                    parsed = self._parse_market(event, mkt_data, game)
                    if parsed is None:
                        continue

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

        logger.info("Discovered %d esports markets total", len(all_markets))
        return all_markets
