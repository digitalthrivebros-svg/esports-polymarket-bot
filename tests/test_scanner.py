"""Basic tests for the scanner module."""

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
