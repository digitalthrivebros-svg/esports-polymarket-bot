"""Tests for the paper trading engine."""

import os
import sqlite3
import pytest
from unittest.mock import patch

# Set up a temp DB for tests before importing modules that use config
os.environ.setdefault("DB_PATH", ":memory:")

from paper_trader import PaperTrader, PaperPosition, normalize_for_compare
from db import init_db, _connect, get_unsettled_trades


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    """Use a fresh SQLite DB for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("config.DB_PATH", db_path)
    monkeypatch.setattr("db.DB_PATH", db_path)
    # Also patch it in paper_trader's db import
    import db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    init_db()
    yield


class TestNormalizeForCompare:
    def test_basic(self) -> None:
        assert normalize_for_compare("G2 Esports") == "g2"

    def test_gaming_suffix(self) -> None:
        assert normalize_for_compare("Bilibili Gaming") == "bilibili"

    def test_already_clean(self) -> None:
        assert normalize_for_compare("fnatic") == "fnatic"


class TestPaperTrader:
    def test_init_default_bankroll(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        assert pt.bankroll == 1000.0
        assert pt.positions == []

    def test_execute_paper_trade(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        result = pt.execute_paper_trade(
            token_id="tok_abc",
            side="BUY",
            price=0.60,
            size=50.0,
            match_id="match_1",
            teams="G2 vs Fnatic",
            team_backed="G2",
            edge=0.05,
        )
        assert result["status"] == "open"
        assert result["size"] == 50.0
        assert result["side"] == "BUY"
        assert pt.bankroll == 950.0
        assert len(pt.positions) == 1

    def test_execute_trade_reduces_bankroll(self) -> None:
        pt = PaperTrader(initial_bankroll=100.0)
        pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.50, size=60.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.05,
        )
        pt.execute_paper_trade(
            token_id="tok2", side="BUY", price=0.50, size=30.0,
            match_id="m2", teams="C vs D", team_backed="C", edge=0.04,
        )
        assert pt.bankroll == 10.0

    def test_insufficient_bankroll(self) -> None:
        pt = PaperTrader(initial_bankroll=10.0)
        result = pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.50, size=50.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.05,
        )
        # Should reduce size to available bankroll
        assert result["size"] == 10.0
        assert pt.bankroll == 0.0

    def test_zero_bankroll_rejected(self) -> None:
        pt = PaperTrader(initial_bankroll=0.0)
        result = pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.50, size=50.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.05,
        )
        assert result["status"] == "rejected"

    def test_settle_match_buy_win(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.40, size=40.0,
            match_id="m1", teams="G2 vs Fnatic", team_backed="G2", edge=0.10,
        )
        assert pt.bankroll == 960.0

        settlements = pt.settle_match("m1", "G2")
        assert len(settlements) == 1
        s = settlements[0]
        assert s["result"] == "won"
        # BUY at 0.40 with $40 → 100 shares → payout $100 → pnl = $60
        assert s["pnl"] == pytest.approx(60.0, abs=0.01)
        assert pt.bankroll == pytest.approx(1060.0, abs=0.01)

    def test_settle_match_buy_loss(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.60, size=60.0,
            match_id="m1", teams="G2 vs Fnatic", team_backed="G2", edge=0.05,
        )
        settlements = pt.settle_match("m1", "Fnatic")
        assert len(settlements) == 1
        s = settlements[0]
        assert s["result"] == "lost"
        assert s["pnl"] == pytest.approx(-60.0, abs=0.01)
        assert pt.bankroll == pytest.approx(940.0, abs=0.01)

    def test_settle_no_matching_trades(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        settlements = pt.settle_match("nonexistent", "G2")
        assert settlements == []

    def test_get_summary(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.50, size=50.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.05,
        )
        pt.settle_match("m1", "A")

        summary = pt.get_summary()
        assert summary["initial_bankroll"] == 1000.0
        assert summary["settled_count"] == 1
        assert summary["open_count"] == 0
        assert summary["wins"] == 1
        assert summary["win_rate"] == 1.0
        assert summary["total_pnl"] > 0

    def test_multiple_trades_same_match(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.50, size=50.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.05,
        )
        pt.execute_paper_trade(
            token_id="tok2", side="BUY", price=0.50, size=30.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.04,
        )
        settlements = pt.settle_match("m1", "A")
        assert len(settlements) == 2
        total_pnl = sum(s["pnl"] for s in settlements)
        assert total_pnl > 0

    def test_settle_idempotent(self) -> None:
        pt = PaperTrader(initial_bankroll=1000.0)
        pt.execute_paper_trade(
            token_id="tok1", side="BUY", price=0.50, size=50.0,
            match_id="m1", teams="A vs B", team_backed="A", edge=0.05,
        )
        settlements1 = pt.settle_match("m1", "A")
        settlements2 = pt.settle_match("m1", "A")
        assert len(settlements1) == 1
        assert len(settlements2) == 0  # Already settled
