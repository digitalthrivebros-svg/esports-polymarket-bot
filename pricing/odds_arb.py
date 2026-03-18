"""Approach A: Pinnacle-based fair-value comparison.

Strips the bookmaker vig from Pinnacle decimal odds and compares the
resulting fair probabilities to Polymarket prices to find edges.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class EdgeSignal:
    """An actionable edge detected between Pinnacle and Polymarket."""

    match_id: str
    team: str
    fair_prob: float
    pm_price: float
    edge: float
    side: str  # "BUY" or "SELL"


def compute_fair_odds(pinnacle_odds_a: float, pinnacle_odds_b: float) -> tuple[float, float]:
    """Remove the vig from Pinnacle decimal odds and return fair probabilities.

    Args:
        pinnacle_odds_a: Decimal odds for team A (e.g. 1.25).
        pinnacle_odds_b: Decimal odds for team B (e.g. 3.80).

    Returns:
        (fair_prob_a, fair_prob_b) that sum to 1.0.
    """
    implied_a = 1.0 / pinnacle_odds_a
    implied_b = 1.0 / pinnacle_odds_b
    total = implied_a + implied_b
    return implied_a / total, implied_b / total


def compute_edge(fair_prob: float, polymarket_price: float) -> float:
    """Return the edge (positive = buy signal).

    Edge = fair probability − Polymarket price.
    """
    return fair_prob - polymarket_price


def find_arb_opportunities(
    pinnacle_odds: dict[str, tuple[float, float]],
    polymarket_prices: dict[str, tuple[float, float]],
    min_edge: float = 0.03,
) -> list[EdgeSignal]:
    """Scan all markets and return edges that exceed *min_edge*.

    Args:
        pinnacle_odds: match_id → (odds_a, odds_b) in decimal format.
        polymarket_prices: match_id → (pm_price_a, pm_price_b) in 0–1 range.
        min_edge: Minimum absolute edge to report.

    Returns:
        A list of :class:`EdgeSignal` for every opportunity found.
    """
    signals: list[EdgeSignal] = []

    for match_id, (odds_a, odds_b) in pinnacle_odds.items():
        if match_id not in polymarket_prices:
            continue

        fair_a, fair_b = compute_fair_odds(odds_a, odds_b)
        pm_a, pm_b = polymarket_prices[match_id]

        edge_a = compute_edge(fair_a, pm_a)
        edge_b = compute_edge(fair_b, pm_b)

        if edge_a >= min_edge:
            signals.append(
                EdgeSignal(
                    match_id=match_id,
                    team="A",
                    fair_prob=fair_a,
                    pm_price=pm_a,
                    edge=edge_a,
                    side="BUY",
                )
            )
        elif edge_a <= -min_edge:
            signals.append(
                EdgeSignal(
                    match_id=match_id,
                    team="A",
                    fair_prob=fair_a,
                    pm_price=pm_a,
                    edge=edge_a,
                    side="SELL",
                )
            )

        if edge_b >= min_edge:
            signals.append(
                EdgeSignal(
                    match_id=match_id,
                    team="B",
                    fair_prob=fair_b,
                    pm_price=pm_b,
                    edge=edge_b,
                    side="BUY",
                )
            )
        elif edge_b <= -min_edge:
            signals.append(
                EdgeSignal(
                    match_id=match_id,
                    team="B",
                    fair_prob=fair_b,
                    pm_price=pm_b,
                    edge=edge_b,
                    side="SELL",
                )
            )

    return signals
