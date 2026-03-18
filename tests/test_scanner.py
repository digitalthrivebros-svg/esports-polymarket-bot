"""Tests for the scanner module."""

import json
from unittest.mock import patch, MagicMock

import requests

from scanner import PolymarketScanner, MarketBook, EsportsMarket


class TestPolymarketScanner:
    def test_init(self) -> None:
        """Scanner can be instantiated."""
        scanner = PolymarketScanner()
        assert scanner.session is not None

    @patch("scanner.requests.Session.get")
    def test_get_midpoint_success(self, mock_get: MagicMock) -> None:
        """Midpoint endpoint returns a float."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"mid": "0.65"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        scanner = PolymarketScanner()
        mid = scanner.get_midpoint("fake_token_123")
        assert mid == 0.65

    @patch("scanner.requests.Session.get")
    def test_get_midpoint_failure(self, mock_get: MagicMock) -> None:
        """Midpoint returns None on request failure."""
        mock_get.side_effect = requests.ConnectionError("network error")
        scanner = PolymarketScanner()
        mid = scanner.get_midpoint("fake_token_123")
        assert mid is None

    @patch("scanner.requests.Session.get")
    def test_get_market_book(self, mock_get: MagicMock) -> None:
        """Order book parsing extracts best bid/ask."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "bids": [{"price": "0.62", "size": "100"}, {"price": "0.60", "size": "200"}],
            "asks": [{"price": "0.65", "size": "150"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        scanner = PolymarketScanner()
        book = scanner.get_market_book("token_abc")
        assert book.best_bid == 0.62
        assert book.best_ask == 0.65
        assert book.bid_liquidity == 300.0
        assert book.ask_liquidity == 150.0

    def test_market_book_dataclass(self) -> None:
        """MarketBook can be created with defaults."""
        book = MarketBook(token_id="test")
        assert book.best_bid == 0.0
        assert book.midpoint == 0.0

    @patch("scanner.requests.Session.get")
    def test_scan_all_esports_empty(self, mock_get: MagicMock) -> None:
        """scan_all_esports returns empty list when no events found."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        scanner = PolymarketScanner()
        markets = scanner.scan_all_esports()
        assert markets == []


class TestParseMarket:
    """Tests for _parse_market with real Gamma API format."""

    def _make_market(self, **overrides) -> dict:
        """Create a market dict matching Gamma API format."""
        base = {
            "conditionId": "0xabc123",
            "clobTokenIds": json.dumps(["token_a", "token_b"]),
            "outcomes": json.dumps(["Team Alpha", "Team Beta"]),
            "outcomePrices": json.dumps(["0.65", "0.35"]),
            "question": "Counter-Strike: Team Alpha vs Team Beta (BO3) - BLAST",
        }
        base.update(overrides)
        return base

    def _make_event(self, **overrides) -> dict:
        base = {"title": "CS2 Match Event", "startDate": "2026-03-18T12:00:00Z"}
        base.update(overrides)
        return base

    def test_parses_json_string_fields(self) -> None:
        """_parse_market correctly parses clobTokenIds and outcomes from JSON strings."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market()

        result = scanner._parse_market(event, market, "cs2")
        assert result is not None
        assert result.condition_id == "0xabc123"
        assert result.token_ids == {"Team Alpha": "token_a", "Team Beta": "token_b"}
        assert result.teams == ["Team Alpha", "Team Beta"]
        assert result.game == "cs2"

    def test_skips_resolved_market(self) -> None:
        """Resolved markets (prices [1,0] or [0,1]) are filtered out."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(outcomePrices=json.dumps(["1", "0"]))
        assert scanner._parse_market(event, market, "cs2") is None

        market2 = self._make_market(outcomePrices=json.dumps(["0", "1"]))
        assert scanner._parse_market(event, market2, "cs2") is None

    def test_skips_near_resolved(self) -> None:
        """Markets with prices like [0.005, 0.995] are also filtered."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(outcomePrices=json.dumps(["0.005", "0.995"]))
        assert scanner._parse_market(event, market, "cs2") is None

    def test_keeps_active_market(self) -> None:
        """Active markets with non-extreme prices are kept."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(outcomePrices=json.dumps(["0.55", "0.45"]))
        result = scanner._parse_market(event, market, "cs2")
        assert result is not None

    def test_no_condition_id(self) -> None:
        """Markets without conditionId are skipped."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(conditionId="")
        assert scanner._parse_market(event, market, "cs2") is None

    def test_no_token_ids(self) -> None:
        """Markets without clobTokenIds are skipped."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(clobTokenIds=json.dumps([]))
        assert scanner._parse_market(event, market, "cs2") is None

    def test_handles_list_format(self) -> None:
        """Fields can also be actual lists (not JSON strings)."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(
            clobTokenIds=["tok1", "tok2"],
            outcomes=["A", "B"],
            outcomePrices=["0.6", "0.4"],
        )
        result = scanner._parse_market(event, market, "lol")
        assert result is not None
        assert result.token_ids == {"A": "tok1", "B": "tok2"}

    def test_malformed_json(self) -> None:
        """Malformed JSON strings don't crash — market is skipped."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(clobTokenIds="not valid json{{{")
        assert scanner._parse_market(event, market, "cs2") is None

    def test_detects_series_format(self) -> None:
        """Series format is extracted from question text."""
        scanner = PolymarketScanner()
        event = self._make_event()

        for fmt in ("BO1", "BO3", "BO5"):
            market = self._make_market(question=f"CS2: A vs B ({fmt}) - Event")
            result = scanner._parse_market(event, market, "cs2")
            assert result is not None
            assert result.series_format == fmt

    def test_generic_outcomes_excluded_from_teams(self) -> None:
        """Yes/No/Over/Under/Odd/Even outcomes are not treated as team names."""
        scanner = PolymarketScanner()
        event = self._make_event()
        market = self._make_market(
            outcomes=json.dumps(["Yes", "No"]),
            outcomePrices=json.dumps(["0.7", "0.3"]),
        )
        result = scanner._parse_market(event, market, "cs2")
        assert result is not None
        assert result.teams == []


class TestIsMatchMarket:
    """Tests for the _is_match_market filter."""

    def test_head_to_head_is_match(self) -> None:
        scanner = PolymarketScanner()
        market = {"outcomes": json.dumps(["FaZe", "Aurora Gaming"])}
        assert scanner._is_match_market(market) is True

    def test_yes_no_is_not_match(self) -> None:
        scanner = PolymarketScanner()
        market = {"outcomes": json.dumps(["Yes", "No"])}
        assert scanner._is_match_market(market) is False

    def test_over_under_is_not_match(self) -> None:
        scanner = PolymarketScanner()
        market = {"outcomes": json.dumps(["Over", "Under"])}
        assert scanner._is_match_market(market) is False

    def test_odd_even_is_not_match(self) -> None:
        scanner = PolymarketScanner()
        market = {"outcomes": json.dumps(["Odd", "Even"])}
        assert scanner._is_match_market(market) is False

    def test_three_outcomes_not_match(self) -> None:
        scanner = PolymarketScanner()
        market = {"outcomes": json.dumps(["A", "B", "C"])}
        assert scanner._is_match_market(market) is False


class TestIsResolved:
    def test_resolved_one_zero(self) -> None:
        assert PolymarketScanner._is_resolved(["1", "0"]) is True

    def test_resolved_zero_one(self) -> None:
        assert PolymarketScanner._is_resolved(["0", "1"]) is True

    def test_active_market(self) -> None:
        assert PolymarketScanner._is_resolved(["0.55", "0.45"]) is False

    def test_near_resolved(self) -> None:
        assert PolymarketScanner._is_resolved(["0.005", "0.995"]) is True

    def test_empty(self) -> None:
        assert PolymarketScanner._is_resolved([]) is False


class TestGetEventsByTagId:
    @patch("scanner.requests.Session.get")
    def test_returns_events(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": "1", "title": "Test"}]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        scanner = PolymarketScanner()
        events = scanner.get_events_by_tag_id("100780")
        assert len(events) == 1

        # Verify tag_id was passed in params
        call_args = mock_get.call_args
        assert call_args[1]["params"]["tag_id"] == "100780"

    @patch("scanner.requests.Session.get")
    def test_returns_empty_on_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.ConnectionError()
        scanner = PolymarketScanner()
        events = scanner.get_events_by_tag_id("100780")
        assert events == []


class TestScanAllEsports:
    @patch("scanner.requests.Session.get")
    def test_filters_and_parses_match_markets(self, mock_get: MagicMock) -> None:
        """scan_all_esports finds match markets and skips resolved/prop markets."""
        fake_event = {
            "title": "CS2 Event",
            "startDate": "2026-03-18T12:00:00Z",
            "markets": [
                # Active match market
                {
                    "conditionId": "0xactive123",
                    "clobTokenIds": json.dumps(["tok1", "tok2"]),
                    "outcomes": json.dumps(["FaZe", "NaVi"]),
                    "outcomePrices": json.dumps(["0.55", "0.45"]),
                    "question": "CS2: FaZe vs NaVi (BO3)",
                },
                # Resolved match market (should be skipped)
                {
                    "conditionId": "0xresolved456",
                    "clobTokenIds": json.dumps(["tok3", "tok4"]),
                    "outcomes": json.dumps(["TeamA", "TeamB"]),
                    "outcomePrices": json.dumps(["1", "0"]),
                    "question": "CS2: TeamA vs TeamB",
                },
                # Prop market (should be skipped by _is_match_market)
                {
                    "conditionId": "0xprop789",
                    "clobTokenIds": json.dumps(["tok5", "tok6"]),
                    "outcomes": json.dumps(["Over", "Under"]),
                    "outcomePrices": json.dumps(["0.5", "0.5"]),
                    "question": "Games Total: O/U 2.5",
                },
            ],
        }

        # First call returns events, subsequent calls return order books
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "/events" in url:
                resp.json.return_value = [fake_event]
            elif "/book" in url:
                resp.json.return_value = {
                    "bids": [{"price": "0.50", "size": "100"}],
                    "asks": [{"price": "0.55", "size": "100"}],
                }
            else:
                resp.json.return_value = {}
            return resp

        mock_get.side_effect = side_effect

        scanner = PolymarketScanner()
        markets = scanner.scan_all_esports(games=["cs2"])

        # Only the active match market should be returned
        assert len(markets) == 1
        assert markets[0].condition_id == "0xactive123"
        assert markets[0].teams == ["FaZe", "NaVi"]
        assert markets[0].series_format == "BO3"
