"""Tests for the matching module — fuzzy team name matching."""

import pytest

from matching import (
    normalize_team_name,
    match_pinnacle_to_polymarket,
    MatchedPair,
    _similarity,
    _extract_pinnacle_odds,
    _extract_pandascore_teams,
)
from scanner import EsportsMarket


class TestNormalizeTeamName:
    def test_lowercase(self) -> None:
        assert normalize_team_name("NAVI") == "navi"

    def test_strip_esports_suffix(self) -> None:
        assert normalize_team_name("G2 Esports") == "g2"

    def test_strip_gaming_suffix(self) -> None:
        assert normalize_team_name("Bilibili Gaming") == "bilibili"

    def test_alias_resolution(self) -> None:
        assert normalize_team_name("Natus Vincere") == "navi"
        assert normalize_team_name("Na'Vi") == "navi"

    def test_cloud9_alias(self) -> None:
        assert normalize_team_name("C9") == "cloud9"

    def test_already_canonical(self) -> None:
        assert normalize_team_name("fnatic") == "fnatic"

    def test_unknown_team_with_suffix(self) -> None:
        # "team" suffix gets stripped by normalize
        assert normalize_team_name("Some Random Team") == "some random"

    def test_no_suffix_to_strip(self) -> None:
        assert normalize_team_name("Spirit") == "spirit"


class TestSimilarity:
    def test_exact_match(self) -> None:
        assert _similarity("G2 Esports", "G2") == 1.0

    def test_high_similarity(self) -> None:
        score = _similarity("Team Liquid", "Liquid")
        assert score == 1.0  # alias resolution

    def test_low_similarity(self) -> None:
        score = _similarity("Fnatic", "Cloud9")
        assert score < 0.5

    def test_same_string(self) -> None:
        assert _similarity("Navi", "Navi") == 1.0


class TestExtractPinnacleOdds:
    def test_valid_fixture(self) -> None:
        fixture = {
            "fixtureId": "id123",
            "bookmakerOdds": {
                "pinnacle": {
                    "markets": {
                        "101": {
                            "outcomes": {
                                "101": {"players": {"0": {"price": 1.25}}},
                                "102": {"players": {"0": {"price": 3.80}}},
                            }
                        }
                    }
                }
            },
        }
        odds = _extract_pinnacle_odds(fixture)
        assert odds == (1.25, 3.80)

    def test_missing_market(self) -> None:
        fixture = {"bookmakerOdds": {"pinnacle": {"markets": {}}}}
        assert _extract_pinnacle_odds(fixture) is None

    def test_missing_bookmaker(self) -> None:
        fixture = {"bookmakerOdds": {}}
        assert _extract_pinnacle_odds(fixture) is None


class TestExtractPandascoreTeams:
    def test_valid_match(self) -> None:
        match = {
            "opponents": [
                {"opponent": {"name": "G2 Esports", "id": 1}},
                {"opponent": {"name": "Fnatic", "id": 2}},
            ]
        }
        teams = _extract_pandascore_teams(match)
        assert teams == ("G2 Esports", "Fnatic")

    def test_single_opponent(self) -> None:
        match = {"opponents": [{"opponent": {"name": "G2"}}]}
        assert _extract_pandascore_teams(match) is None

    def test_empty_opponents(self) -> None:
        match = {"opponents": []}
        assert _extract_pandascore_teams(match) is None


class TestMatchPinnacleToPolymarket:
    def _make_market(self, teams: list[str], game: str = "cs2") -> EsportsMarket:
        return EsportsMarket(
            condition_id=f"cond_{teams[0]}_{teams[1]}",
            question=f"Who will win? {teams[0]} vs {teams[1]}",
            token_ids={"Yes": "token_a", "No": "token_b"},
            teams=teams,
            game=game,
        )

    def test_match_found(self) -> None:
        markets = [self._make_market(["G2", "Fnatic"])]
        pinnacle = {
            "cs2": [
                {
                    "fixtureId": "fix1",
                    "bookmakerOdds": {
                        "pinnacle": {
                            "markets": {
                                "101": {
                                    "outcomes": {
                                        "101": {"players": {"0": {"price": 1.50}}},
                                        "102": {"players": {"0": {"price": 2.50}}},
                                    }
                                }
                            }
                        }
                    },
                }
            ]
        }
        pandascore = {
            "csgo": [
                {
                    "id": 12345,
                    "opponents": [
                        {"opponent": {"name": "G2 Esports"}},
                        {"opponent": {"name": "Fnatic"}},
                    ],
                }
            ]
        }
        result = match_pinnacle_to_polymarket(pinnacle, markets, pandascore, min_confidence=0.6)
        assert len(result) == 1
        assert result[0].team_a == "G2"
        assert result[0].team_b == "Fnatic"
        assert result[0].confidence > 0.6

    def test_no_match_low_confidence(self) -> None:
        markets = [self._make_market(["RandomTeamX", "RandomTeamY"])]
        pinnacle = {"cs2": []}
        pandascore = {
            "csgo": [
                {
                    "id": 1,
                    "opponents": [
                        {"opponent": {"name": "Totally Different A"}},
                        {"opponent": {"name": "Totally Different B"}},
                    ],
                }
            ]
        }
        result = match_pinnacle_to_polymarket(pinnacle, markets, pandascore, min_confidence=0.6)
        assert len(result) == 0

    def test_empty_inputs(self) -> None:
        result = match_pinnacle_to_polymarket({}, [], {})
        assert result == []

    def test_single_team_market_skipped(self) -> None:
        market = EsportsMarket(
            condition_id="cond1",
            teams=["OnlyOneTeam"],
            game="cs2",
        )
        result = match_pinnacle_to_polymarket({"cs2": []}, [market], {"csgo": []})
        assert result == []
