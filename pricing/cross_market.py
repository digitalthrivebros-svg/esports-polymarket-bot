"""Approach C: Cross-market consistency checks.

Detects mispriced sub-markets by verifying that per-game, handicap, and
total-games lines are internally consistent with the moneyline.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InconsistencySignal:
    """A detected inconsistency between sub-markets."""

    match_id: str
    description: str
    expected: float
    actual: float
    discrepancy: float  # actual - expected
    market_type: str  # e.g. "game_1", "handicap_-1.5", "total_3.5"


class CrossMarketChecker:
    """Checks consistency across moneyline, per-game, handicap, and total sub-markets."""

    def __init__(self, tolerance: float = 0.05) -> None:
        self.tolerance = tolerance

    @staticmethod
    def _implied_bo3_moneyline(game1_prob: float) -> float:
        """Derive BO3 moneyline from a per-game win probability."""
        p = game1_prob
        return p**2 * (3.0 - 2.0 * p)

    @staticmethod
    def _implied_handicap_minus_1_5(p: float) -> float:
        """Probability of team winning 2-0 in a BO3 (covers -1.5 handicap)."""
        return p**2

    @staticmethod
    def _implied_over_3_games(p: float) -> float:
        """Probability that a BO3 goes to 3 games (either team wins 2-1)."""
        return 2.0 * p * (1.0 - p)

    @staticmethod
    def _implied_over_4_games_bo5(p: float) -> float:
        """Probability of 4+ games in a BO5 = 1 - P(3-0 by either side)."""
        p_3_0 = p**3 + (1.0 - p) ** 3
        return 1.0 - p_3_0

    def check_consistency(self, match_markets: dict[str, Any]) -> list[InconsistencySignal]:
        """Verify internal consistency across a set of sub-markets.

        Args:
            match_markets: Dict with keys like:
                - "match_id": str
                - "moneyline_a": float (PM price for team A)
                - "game_1_a": float (PM price for team A winning game 1)
                - "handicap_-1.5_a": float (PM price for team A -1.5)
                - "total_over_3.5": float (PM price for over 3.5 games)
                - "format": "BO3" | "BO5"

        Returns:
            List of inconsistency signals.
        """
        signals: list[InconsistencySignal] = []
        match_id = match_markets.get("match_id", "unknown")
        moneyline_a = match_markets.get("moneyline_a")
        game_1_a = match_markets.get("game_1_a")
        handicap_a = match_markets.get("handicap_-1.5_a")
        total_over = match_markets.get("total_over_3.5")
        fmt = match_markets.get("format", "BO3").upper()

        # Check 1: Game 1 price vs moneyline consistency
        if game_1_a is not None and moneyline_a is not None and fmt == "BO3":
            implied_ml = self._implied_bo3_moneyline(game_1_a)
            diff = moneyline_a - implied_ml
            if abs(diff) > self.tolerance:
                signals.append(
                    InconsistencySignal(
                        match_id=match_id,
                        description=(
                            f"Game-1 price ({game_1_a:.2f}) implies moneyline "
                            f"{implied_ml:.2f}, but actual is {moneyline_a:.2f}"
                        ),
                        expected=implied_ml,
                        actual=moneyline_a,
                        discrepancy=diff,
                        market_type="game_1",
                    )
                )

        # Check 2: Handicap -1.5 vs per-game model
        if handicap_a is not None and game_1_a is not None and fmt == "BO3":
            implied_hc = self._implied_handicap_minus_1_5(game_1_a)
            diff = handicap_a - implied_hc
            if abs(diff) > self.tolerance:
                signals.append(
                    InconsistencySignal(
                        match_id=match_id,
                        description=(
                            f"Handicap -1.5 ({handicap_a:.2f}) inconsistent with "
                            f"game-1 implied 2-0 prob {implied_hc:.2f}"
                        ),
                        expected=implied_hc,
                        actual=handicap_a,
                        discrepancy=diff,
                        market_type="handicap_-1.5",
                    )
                )

        # Check 3: Over 3.5 games in BO5
        if total_over is not None and game_1_a is not None and fmt == "BO5":
            implied_over = self._implied_over_4_games_bo5(game_1_a)
            diff = total_over - implied_over
            if abs(diff) > self.tolerance:
                signals.append(
                    InconsistencySignal(
                        match_id=match_id,
                        description=(
                            f"Over 3.5 games ({total_over:.2f}) inconsistent with "
                            f"per-game implied {implied_over:.2f}"
                        ),
                        expected=implied_over,
                        actual=total_over,
                        discrepancy=diff,
                        market_type="total_3.5",
                    )
                )

        return signals

    def find_mispriced_legs(
        self, match_markets: dict[str, Any]
    ) -> list[InconsistencySignal]:
        """Alias for check_consistency — returns all mispriced sub-markets."""
        return self.check_consistency(match_markets)
