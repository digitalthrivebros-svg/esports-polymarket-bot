"""Unit tests for the risk module."""

import pytest

from risk import RiskManager


@pytest.fixture
def rm() -> RiskManager:
    """Default RiskManager with standard limits."""
    return RiskManager(
        max_position_per_match=100,
        max_total_exposure=500,
        max_daily_loss=50,
        min_edge_threshold=0.03,
        max_matches_concurrent=10,
    )


# ── should_trade tests ───────────────────────────────────────────────

class TestShouldTrade:
    def test_below_edge_threshold(self, rm: RiskManager) -> None:
        """Edge of 2 cents is below the 3-cent threshold → reject."""
        assert rm.should_trade(edge=0.02, current_exposure=100, daily_pnl=0) is False

    def test_sufficient_edge(self, rm: RiskManager) -> None:
        """Edge of 5 cents with room to trade → accept."""
        assert rm.should_trade(edge=0.05, current_exposure=100, daily_pnl=0) is True

    def test_kill_switch_triggered(self, rm: RiskManager) -> None:
        """Daily P&L exceeds max loss → kill switch stops trading."""
        assert rm.should_trade(edge=0.05, current_exposure=100, daily_pnl=-60) is False

    def test_max_exposure_reached(self, rm: RiskManager) -> None:
        """Current exposure at the limit → reject."""
        assert rm.should_trade(edge=0.05, current_exposure=500, daily_pnl=0) is False

    def test_max_concurrent_matches(self, rm: RiskManager) -> None:
        """Already at max concurrent matches → reject."""
        assert rm.should_trade(
            edge=0.05, current_exposure=100, daily_pnl=0, concurrent_matches=10
        ) is False

    def test_negative_pnl_within_limit(self, rm: RiskManager) -> None:
        """Down $40 is still within the $50 limit → accept."""
        assert rm.should_trade(edge=0.05, current_exposure=100, daily_pnl=-40) is True

    def test_exactly_at_loss_limit(self, rm: RiskManager) -> None:
        """At exactly -$50 daily → should still trade (boundary is < not <=)."""
        assert rm.should_trade(edge=0.05, current_exposure=100, daily_pnl=-50) is True

    def test_just_over_loss_limit(self, rm: RiskManager) -> None:
        """At -$50.01 → kill switch fires."""
        assert rm.should_trade(edge=0.05, current_exposure=100, daily_pnl=-50.01) is False


# ── position_size tests ──────────────────────────────────────────────

class TestPositionSize:
    def test_typical_edge(self, rm: RiskManager) -> None:
        """Quarter-Kelly with 5% edge on $1000 bankroll ≈ $13.16."""
        size = rm.position_size(edge=0.05, bankroll=1000)
        assert 13.0 <= size <= 14.0

    def test_capped_at_max(self, rm: RiskManager) -> None:
        """Very large bankroll → capped at MAX_POSITION_PER_MATCH."""
        size = rm.position_size(edge=0.10, bankroll=100_000)
        assert size == 100.0

    def test_zero_edge(self, rm: RiskManager) -> None:
        """Zero edge → zero position."""
        assert rm.position_size(edge=0.0, bankroll=1000) == 0.0

    def test_negative_edge(self, rm: RiskManager) -> None:
        """Negative edge → zero position."""
        assert rm.position_size(edge=-0.05, bankroll=1000) == 0.0

    def test_edge_near_one(self, rm: RiskManager) -> None:
        """Edge >= 1 is invalid → zero position."""
        assert rm.position_size(edge=1.0, bankroll=1000) == 0.0
