"""Module 5: Position sizing, exposure limits, and kill switches."""

import logging

from config import (
    RISK_MAX_POSITION_PER_MATCH,
    RISK_MAX_TOTAL_EXPOSURE,
    RISK_MAX_DAILY_LOSS,
    RISK_MIN_EDGE_THRESHOLD,
    RISK_MAX_MATCHES_CONCURRENT,
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces risk limits and computes position sizes.

    All limits are loaded from environment-variable configuration at import
    time and can be overridden through the constructor for testing.
    """

    def __init__(
        self,
        max_position_per_match: float = RISK_MAX_POSITION_PER_MATCH,
        max_total_exposure: float = RISK_MAX_TOTAL_EXPOSURE,
        max_daily_loss: float = RISK_MAX_DAILY_LOSS,
        min_edge_threshold: float = RISK_MIN_EDGE_THRESHOLD,
        max_matches_concurrent: int = RISK_MAX_MATCHES_CONCURRENT,
    ) -> None:
        self.max_position_per_match = max_position_per_match
        self.max_total_exposure = max_total_exposure
        self.max_daily_loss = max_daily_loss
        self.min_edge_threshold = min_edge_threshold
        self.max_matches_concurrent = max_matches_concurrent

    def should_trade(
        self,
        edge: float,
        current_exposure: float,
        daily_pnl: float,
        concurrent_matches: int = 0,
    ) -> bool:
        """Decide whether a new trade is permitted.

        Returns False (and logs the reason) when any limit is breached.
        """
        if daily_pnl < -self.max_daily_loss:
            logger.warning(
                "Kill switch: daily P&L %.2f exceeds max loss -%.2f",
                daily_pnl, self.max_daily_loss,
            )
            return False

        if current_exposure >= self.max_total_exposure:
            logger.warning(
                "Max total exposure %.2f reached (limit %.2f)",
                current_exposure, self.max_total_exposure,
            )
            return False

        if abs(edge) < self.min_edge_threshold:
            logger.debug(
                "Edge %.4f below threshold %.4f — skipping",
                edge, self.min_edge_threshold,
            )
            return False

        if concurrent_matches >= self.max_matches_concurrent:
            logger.warning(
                "Concurrent-match limit reached (%d/%d)",
                concurrent_matches, self.max_matches_concurrent,
            )
            return False

        return True

    def position_size(self, edge: float, bankroll: float) -> float:
        """Compute position size using quarter-Kelly criterion.

        Kelly fraction for a binary bet: f* = edge / (1 - edge).
        We use 25 % of Kelly for safety, capped at MAX_POSITION_PER_MATCH.
        """
        if edge <= 0 or edge >= 1:
            return 0.0

        kelly_fraction = edge / (1 - edge)
        size = bankroll * kelly_fraction * 0.25  # quarter-Kelly
        size = min(size, self.max_position_per_match)
        return round(size, 2)
