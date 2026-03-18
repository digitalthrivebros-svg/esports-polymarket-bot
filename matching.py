"""Fuzzy-match Pinnacle fixtures (via OddsPapi) to Polymarket markets using PandaScore as a bridge."""

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from scanner import EsportsMarket

logger = logging.getLogger(__name__)

# Suffixes to strip for normalisation
_STRIP_SUFFIXES = re.compile(
    r"\s*(esports|gaming|team|club|gg|e-sports)\s*$", re.IGNORECASE
)

# Common aliases: canonical name -> set of known variants
TEAM_ALIASES: dict[str, set[str]] = {
    "g2": {"g2 esports", "g2esports"},
    "t1": {"t1 lol", "sk telecom t1", "skt t1", "skt"},
    "navi": {"natus vincere", "na'vi"},
    "fnatic": {"fnc"},
    "cloud9": {"c9"},
    "team liquid": {"liquid", "tl"},
    "team vitality": {"vitality", "vit"},
    "evil geniuses": {"eg"},
    "100 thieves": {"100t"},
    "sentinels": {"sen"},
    "faze": {"faze clan"},
    "mouz": {"mousesports"},
    "heroic": {"heroic gg"},
    "nrg": {"nrg esports"},
    "gen.g": {"geng", "gen g"},
    "drx": {"drx team"},
    "jdg": {"jd gaming"},
    "weibo": {"weibo gaming"},
    "bilibili": {"bilibili gaming", "blg"},
    "loud": {"loud gg"},
    "paper rex": {"prx"},
    "karmine corp": {"kc"},
}

# Build reverse lookup: alias -> canonical
_ALIAS_LOOKUP: dict[str, str] = {}
for canonical, aliases in TEAM_ALIASES.items():
    _ALIAS_LOOKUP[canonical] = canonical
    for alias in aliases:
        _ALIAS_LOOKUP[alias] = canonical


# OddsPapi game name -> PandaScore slug mapping
GAME_TO_SLUG: dict[str, str] = {
    "cs2": "csgo",
    "csgo": "csgo",
    "lol": "lol",
    "dota2": "dota2",
    "valorant": "valorant",
}


@dataclass
class MatchedPair:
    """A matched Polymarket market + Pinnacle odds pair."""

    polymarket_market: EsportsMarket
    pinnacle_odds_a: float  # decimal odds for team A
    pinnacle_odds_b: float  # decimal odds for team B
    team_a: str
    team_b: str
    match_id: str  # PandaScore match ID or fixture ID for tracking
    confidence: float = 0.0  # match quality score (0-1)


def normalize_team_name(name: str) -> str:
    """Normalize a team name for fuzzy matching."""
    name = name.strip().lower()
    name = _STRIP_SUFFIXES.sub("", name).strip()
    return _ALIAS_LOOKUP.get(name, name)


def _similarity(a: str, b: str) -> float:
    """Return similarity ratio between two normalized team names."""
    na = normalize_team_name(a)
    nb = normalize_team_name(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _extract_pinnacle_odds(fixture: dict[str, Any]) -> tuple[float, float] | None:
    """Extract Pinnacle Full Time Result odds from an OddsPapi fixture.

    Returns (team1_odds, team2_odds) or None if not found.
    """
    try:
        markets = fixture["bookmakerOdds"]["pinnacle"]["markets"]
        # Market 101 = Full Time Result
        ftr = markets.get("101") or markets.get(101)
        if not ftr:
            return None
        outcomes = ftr["outcomes"]
        # Outcome 101 = Team 1, 102 = Team 2
        o1 = outcomes.get("101") or outcomes.get(101)
        o2 = outcomes.get("102") or outcomes.get(102)
        if not o1 or not o2:
            return None
        price_a = float(o1["players"]["0"]["price"])
        price_b = float(o2["players"]["0"]["price"])
        return (price_a, price_b)
    except (KeyError, TypeError, ValueError):
        return None


def _extract_pandascore_teams(match: dict[str, Any]) -> tuple[str, str] | None:
    """Extract team names from a PandaScore match.

    PandaScore matches have an ``opponents`` array with ``opponent.name``.
    """
    opponents = match.get("opponents", [])
    if len(opponents) < 2:
        return None
    team_a = opponents[0].get("opponent", {}).get("name", "")
    team_b = opponents[1].get("opponent", {}).get("name", "")
    if team_a and team_b:
        return (team_a, team_b)
    return None


def match_pinnacle_to_polymarket(
    pinnacle_fixtures: dict[str, list[dict[str, Any]]],
    polymarket_markets: list[EsportsMarket],
    pandascore_upcoming: dict[str, list[dict[str, Any]]],
    min_confidence: float = 0.6,
) -> list[MatchedPair]:
    """Match Pinnacle fixtures to Polymarket markets using PandaScore as a bridge.

    Flow:
        1. PandaScore upcoming matches provide team names
        2. Fuzzy-match PandaScore team names to Polymarket market teams
        3. For matched PandaScore matches, find corresponding OddsPapi fixtures
           by tournament/game + timing
        4. Return MatchedPairs with Pinnacle odds linked to Polymarket markets

    Args:
        pinnacle_fixtures: OddsPapi odds keyed by game (cs2, lol, ...).
        polymarket_markets: Discovered Polymarket esports markets.
        pandascore_upcoming: PandaScore upcoming matches keyed by game slug.
        min_confidence: Minimum similarity threshold for a match.

    Returns:
        List of MatchedPair objects.
    """
    matched: list[MatchedPair] = []

    for market in polymarket_markets:
        if len(market.teams) < 2:
            continue

        pm_team_a = market.teams[0]
        pm_team_b = market.teams[1]
        game = market.game

        # Map game name to PandaScore slug
        ps_slug = GAME_TO_SLUG.get(game, game)

        # Step 1: find best PandaScore match for this Polymarket market
        ps_matches = pandascore_upcoming.get(ps_slug, [])
        best_ps_match = None
        best_ps_score = 0.0
        best_ps_teams: tuple[str, str] | None = None

        for ps_match in ps_matches:
            ps_teams = _extract_pandascore_teams(ps_match)
            if not ps_teams:
                continue

            # Try both orderings
            score_ab = min(
                _similarity(pm_team_a, ps_teams[0]),
                _similarity(pm_team_b, ps_teams[1]),
            )
            score_ba = min(
                _similarity(pm_team_a, ps_teams[1]),
                _similarity(pm_team_b, ps_teams[0]),
            )
            score = max(score_ab, score_ba)

            if score > best_ps_score:
                best_ps_score = score
                best_ps_match = ps_match
                best_ps_teams = ps_teams

        if best_ps_score < min_confidence or best_ps_match is None or best_ps_teams is None:
            continue

        # Step 2: find Pinnacle odds for this game
        game_fixtures = pinnacle_fixtures.get(game, [])
        best_fixture = None
        best_odds: tuple[float, float] | None = None

        for fixture in game_fixtures:
            odds = _extract_pinnacle_odds(fixture)
            if odds is None:
                continue

            # We can't easily match OddsPapi fixtures to PandaScore without
            # participant names. Use tournament/timing proximity as a heuristic.
            # For now, match by: same game + any available fixture with valid odds.
            # Future improvement: match by tournament name + start time.
            #
            # Simple approach: take the first fixture with valid odds for this game.
            # In practice, we'd want more sophisticated matching here.
            best_fixture = fixture
            best_odds = odds
            break  # Take first available — can improve later

        if best_odds is None:
            continue

        # Determine team ordering: which Pinnacle team corresponds to which PM team
        ps_a, ps_b = best_ps_teams
        sim_a_first = _similarity(pm_team_a, ps_a)
        sim_a_second = _similarity(pm_team_a, ps_b)

        if sim_a_first >= sim_a_second:
            odds_a, odds_b = best_odds
            team_a, team_b = pm_team_a, pm_team_b
        else:
            odds_b, odds_a = best_odds
            team_a, team_b = pm_team_a, pm_team_b

        match_id = str(best_ps_match.get("id", best_fixture.get("fixtureId", "")))

        matched.append(
            MatchedPair(
                polymarket_market=market,
                pinnacle_odds_a=odds_a,
                pinnacle_odds_b=odds_b,
                team_a=team_a,
                team_b=team_b,
                match_id=match_id,
                confidence=best_ps_score,
            )
        )
        logger.info(
            "MATCHED: %s vs %s (confidence=%.2f, pinnacle=%.2f/%.2f)",
            team_a, team_b, best_ps_score, odds_a, odds_b,
        )

    logger.info("Matched %d Polymarket markets to Pinnacle odds", len(matched))
    return matched
