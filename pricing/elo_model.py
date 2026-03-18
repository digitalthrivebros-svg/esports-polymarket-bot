"""Approach B: Glicko-2 rating system for esports teams.

Maintains per-team ratings and converts them into match-win probabilities,
including adjustments for Best-of-3 and Best-of-5 series formats.
"""

import math
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Glicko-2 constants
INITIAL_RATING = 1500.0
INITIAL_RD = 350.0
INITIAL_VOLATILITY = 0.06
TAU = 0.5  # system constant constraining volatility change
CONVERGENCE_TOLERANCE = 1e-6


@dataclass
class TeamRating:
    """Glicko-2 rating for a single team."""

    rating: float = INITIAL_RATING
    rd: float = INITIAL_RD
    volatility: float = INITIAL_VOLATILITY


def _g(rd: float) -> float:
    """Glicko-2 g-function: reduces impact of opponents with high RD."""
    return 1.0 / math.sqrt(1.0 + 3.0 * rd**2 / math.pi**2)


def _e(rating: float, opp_rating: float, opp_rd: float) -> float:
    """Expected score of *rating* vs. *opp_rating* (with opponent RD)."""
    return 1.0 / (1.0 + math.exp(-_g(opp_rd) * (rating - opp_rating)))


def glicko_to_prob(
    rating_a: float,
    rating_b: float,
    rd_a: float = INITIAL_RD,
    rd_b: float = INITIAL_RD,
) -> float:
    """Convert two Glicko-2 ratings into a win probability for team A.

    Uses the combined RD of both teams.
    """
    combined_rd = math.sqrt(rd_a**2 + rd_b**2)
    return 1.0 / (1.0 + math.exp(-_g(combined_rd) * (rating_a - rating_b)))


def bo3_prob(p: float) -> float:
    """Probability of winning a Best-of-3 given per-map win probability *p*.

    P(win BO3) = p^2 * (3 - 2p)
    """
    return p**2 * (3.0 - 2.0 * p)


def bo5_prob(p: float) -> float:
    """Probability of winning a Best-of-5 given per-map win probability *p*.

    P(win BO5) = p^3 * (10 - 15p + 6p^2)
    """
    return p**3 * (10.0 - 15.0 * p + 6.0 * p**2)


class GlickoModel:
    """Maintains Glicko-2 ratings for all known teams and produces predictions."""

    def __init__(self) -> None:
        self.ratings: dict[str, TeamRating] = {}

    def _ensure_team(self, team: str) -> TeamRating:
        if team not in self.ratings:
            self.ratings[team] = TeamRating()
        return self.ratings[team]

    def update_rating(self, team: str, opponent: str, result: float) -> None:
        """Update *team*'s rating after a match (result: 1 = win, 0 = loss, 0.5 = draw).

        Implements the simplified Glicko-2 single-game update.
        """
        tr = self._ensure_team(team)
        opp = self._ensure_team(opponent)

        # Convert to Glicko-2 scale (μ, φ)
        mu = (tr.rating - 1500.0) / 173.7178
        phi = tr.rd / 173.7178
        opp_mu = (opp.rating - 1500.0) / 173.7178
        opp_phi = opp.rd / 173.7178

        g_val = _g(opp_phi)
        e_val = 1.0 / (1.0 + math.exp(-g_val * (mu - opp_mu)))
        v = 1.0 / (g_val**2 * e_val * (1.0 - e_val))

        delta = v * g_val * (result - e_val)

        # Simplified volatility update (Illinois algorithm)
        a = math.log(tr.volatility**2)
        A = a

        if delta**2 > phi**2 + v:
            B = math.log(delta**2 - phi**2 - v)
        else:
            k = 1
            while self._f(a - k * TAU, delta, phi, v, a) < 0:
                k += 1
            B = a - k * TAU

        f_A = self._f(A, delta, phi, v, a)
        f_B = self._f(B, delta, phi, v, a)

        for _ in range(100):
            if abs(B - A) < CONVERGENCE_TOLERANCE:
                break
            C = A + (A - B) * f_A / (f_B - f_A)
            f_C = self._f(C, delta, phi, v, a)
            if f_C * f_B <= 0:
                A = B
                f_A = f_B
            else:
                f_A /= 2.0
            B = C
            f_B = f_C

        new_vol = math.exp(A / 2.0)
        phi_star = math.sqrt(phi**2 + new_vol**2)
        new_phi = 1.0 / math.sqrt(1.0 / phi_star**2 + 1.0 / v)
        new_mu = mu + new_phi**2 * g_val * (result - e_val)

        # Convert back to Glicko-2 rating scale
        tr.rating = 173.7178 * new_mu + 1500.0
        tr.rd = 173.7178 * new_phi
        tr.volatility = new_vol

        logger.debug(
            "Updated %s: rating=%.1f rd=%.1f vol=%.4f",
            team, tr.rating, tr.rd, tr.volatility,
        )

    @staticmethod
    def _f(x: float, delta: float, phi: float, v: float, a: float) -> float:
        ex = math.exp(x)
        num = ex * (delta**2 - phi**2 - v - ex)
        denom = 2.0 * (phi**2 + v + ex) ** 2
        return num / denom - (x - a) / TAU**2

    def predict(self, team_a: str, team_b: str, series_format: str = "BO1") -> float:
        """Predict team A's win probability.

        Args:
            team_a: Team A identifier.
            team_b: Team B identifier.
            series_format: "BO1", "BO3", or "BO5".

        Returns:
            Probability (0–1) that team A wins the series.
        """
        ra = self._ensure_team(team_a)
        rb = self._ensure_team(team_b)

        map_prob = glicko_to_prob(ra.rating, rb.rating, ra.rd, rb.rd)

        fmt = series_format.upper()
        if fmt == "BO3":
            return bo3_prob(map_prob)
        elif fmt == "BO5":
            return bo5_prob(map_prob)
        return map_prob  # BO1 or unknown
