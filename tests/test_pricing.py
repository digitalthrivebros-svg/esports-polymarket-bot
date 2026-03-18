"""Unit tests for pricing modules (odds_arb, elo_model)."""

import pytest

from pricing.odds_arb import compute_fair_odds, compute_edge, find_arb_opportunities
from pricing.elo_model import bo3_prob, bo5_prob, glicko_to_prob, GlickoModel


# ── odds_arb tests ───────────────────────────────────────────────────

class TestComputeFairOdds:
    def test_standard_line(self) -> None:
        """Pinnacle 1.25 / 3.80 → roughly 0.752 / 0.248 after vig removal."""
        fair_a, fair_b = compute_fair_odds(1.25, 3.80)
        assert abs(fair_a + fair_b - 1.0) < 1e-9, "Fair probs must sum to 1"
        assert 0.74 < fair_a < 0.77
        assert 0.23 < fair_b < 0.27

    def test_even_odds(self) -> None:
        """Equal odds → 50/50."""
        fair_a, fair_b = compute_fair_odds(2.0, 2.0)
        assert abs(fair_a - 0.5) < 1e-9
        assert abs(fair_b - 0.5) < 1e-9

    def test_heavy_favourite(self) -> None:
        """1.05 / 15.0 → very lopsided."""
        fair_a, fair_b = compute_fair_odds(1.05, 15.0)
        assert fair_a > 0.90
        assert fair_b < 0.10


class TestComputeEdge:
    def test_positive_edge(self) -> None:
        """Fair prob above PM price → positive edge (buy)."""
        assert compute_edge(0.70, 0.60) == pytest.approx(0.10)

    def test_negative_edge(self) -> None:
        """Fair prob below PM price → negative edge (sell)."""
        assert compute_edge(0.50, 0.60) == pytest.approx(-0.10)

    def test_zero_edge(self) -> None:
        assert compute_edge(0.55, 0.55) == pytest.approx(0.0)


class TestFindArbOpportunities:
    def test_finds_edge(self) -> None:
        odds = {"m1": (1.25, 3.80)}
        # fair_a ≈ 0.752 → buying at 0.70 gives ~5c edge
        prices = {"m1": (0.70, 0.30)}
        signals = find_arb_opportunities(odds, prices, min_edge=0.03)
        assert len(signals) >= 1
        assert any(s.side == "BUY" and s.team == "A" for s in signals)

    def test_no_edge(self) -> None:
        odds = {"m1": (2.0, 2.0)}  # fair 50/50
        prices = {"m1": (0.50, 0.50)}  # PM at fair value
        signals = find_arb_opportunities(odds, prices, min_edge=0.03)
        assert len(signals) == 0


# ── elo_model tests ──────────────────────────────────────────────────

class TestBO3Prob:
    def test_at_60_percent(self) -> None:
        """bo3_prob(0.60) ≈ 0.648."""
        result = bo3_prob(0.60)
        assert abs(result - 0.648) < 0.001

    def test_at_50_percent(self) -> None:
        """bo3_prob(0.50) = 0.50 (symmetric)."""
        assert abs(bo3_prob(0.50) - 0.50) < 1e-9

    def test_at_100_percent(self) -> None:
        assert abs(bo3_prob(1.0) - 1.0) < 1e-9

    def test_at_0_percent(self) -> None:
        assert abs(bo3_prob(0.0) - 0.0) < 1e-9


class TestBO5Prob:
    def test_at_60_percent(self) -> None:
        """bo5_prob(0.60) ≈ 0.683."""
        result = bo5_prob(0.60)
        assert abs(result - 0.683) < 0.001

    def test_at_50_percent(self) -> None:
        assert abs(bo5_prob(0.50) - 0.50) < 1e-9


class TestGlickoToProb:
    def test_equal_ratings(self) -> None:
        """Equal ratings → 50%."""
        prob = glicko_to_prob(1500, 1500)
        assert abs(prob - 0.5) < 0.01

    def test_higher_rating_favoured(self) -> None:
        """Higher rated team should have > 50% win probability."""
        prob = glicko_to_prob(1600, 1400)
        assert prob > 0.5


class TestGlickoModel:
    def test_predict_equal(self) -> None:
        """Unknown teams start at 1500 → ~50%."""
        model = GlickoModel()
        prob = model.predict("TeamX", "TeamY", "BO1")
        assert abs(prob - 0.5) < 0.01

    def test_update_and_predict(self) -> None:
        """After a win, the winner should be favoured."""
        model = GlickoModel()
        model.update_rating("Winner", "Loser", 1.0)
        prob = model.predict("Winner", "Loser", "BO1")
        assert prob > 0.5
