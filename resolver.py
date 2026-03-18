"""Match result resolution — polls PandaScore for completed matches and settles paper trades."""

import logging
from datetime import date
from typing import Any

from data_ingest.pandascore import PandaScoreClient, GAME_SLUGS
from paper_trader import PaperTrader, normalize_for_compare
from db import get_unsettled_trades, update_daily_pnl, get_daily_pnl
from matching import normalize_team_name

logger = logging.getLogger(__name__)


class MatchResolver:
    """Polls for completed match results and settles paper trades."""

    def __init__(self, pandascore: PandaScoreClient, paper_trader: PaperTrader) -> None:
        self.pandascore = pandascore
        self.paper_trader = paper_trader

    def resolve_completed_matches(self) -> list[dict[str, Any]]:
        """Check for finished matches and settle corresponding paper trades.

        Steps:
            1. Get all open paper trades from DB
            2. Get unique match_ids
            3. For each, check PandaScore past matches for results
            4. If match is finished, settle via PaperTrader
            5. Update DB: trade status, pnl, fill_price=1.0 or 0.0
            6. Update daily_pnl table
            7. Return list of settlements for logging
        """
        # 1. Get open trades
        open_trades = get_unsettled_trades()
        if not open_trades:
            logger.debug("No unsettled trades to resolve")
            return []

        # 2. Collect unique match IDs
        match_ids = {t.get("match_id", "") for t in open_trades if t.get("match_id")}
        if not match_ids:
            return []

        logger.info("Checking %d open match(es) for results…", len(match_ids))

        # 3. Fetch past matches from PandaScore (last 3 days)
        past_matches = self.pandascore.get_all_past_matches(days_back=3)

        # Build a lookup of PandaScore match results
        # Key: match ID (str), Value: winner team name
        results_by_id: dict[str, str] = {}
        results_by_teams: dict[str, str] = {}

        for game, matches in past_matches.items():
            for match in matches:
                winner = match.get("winner")
                if not winner:
                    continue
                winner_name = winner.get("name", "")
                if not winner_name:
                    continue

                # Store by PandaScore match ID
                ps_id = str(match.get("id", ""))
                if ps_id:
                    results_by_id[ps_id] = winner_name

                # Also store by team pair for fallback matching
                opponents = match.get("opponents", [])
                if len(opponents) >= 2:
                    t1 = opponents[0].get("opponent", {}).get("name", "")
                    t2 = opponents[1].get("opponent", {}).get("name", "")
                    if t1 and t2:
                        key = _make_team_pair_key(t1, t2)
                        results_by_teams[key] = winner_name

        # 4. Match and settle
        all_settlements: list[dict[str, Any]] = []
        settled_match_ids: set[str] = set()

        for match_id in match_ids:
            winner_name = results_by_id.get(match_id)

            # Fallback: try matching by team names from the trade record
            if not winner_name:
                trades_for_match = [t for t in open_trades if t.get("match_id") == match_id]
                for t in trades_for_match:
                    teams_str = t.get("teams", "")
                    if " vs " in teams_str:
                        parts = teams_str.split(" vs ", 1)
                        key = _make_team_pair_key(parts[0], parts[1])
                        winner_name = results_by_teams.get(key)
                        if winner_name:
                            break

            if not winner_name:
                continue

            # 5. Settle via paper trader
            settlements = self.paper_trader.settle_match(match_id, winner_name)
            all_settlements.extend(settlements)
            settled_match_ids.add(match_id)

        # 6. Update daily P&L
        if all_settlements:
            self._update_daily_pnl(all_settlements)
            logger.info(
                "Resolved %d match(es), settled %d trade(s)",
                len(settled_match_ids), len(all_settlements),
            )

        return all_settlements

    def _update_daily_pnl(self, settlements: list[dict[str, Any]]) -> None:
        """Update the daily_pnl table with settlement results."""
        today = date.today()
        current = get_daily_pnl(today)

        realized_pnl = current.get("realized_pnl", 0.0) + sum(s["pnl"] for s in settlements)
        num_trades = current.get("num_trades", 0) + len(settlements)
        wins = sum(1 for s in settlements if s["pnl"] > 0)
        existing_wins = current.get("win_rate", 0.0) * current.get("num_trades", 0)
        total_wins = existing_wins + wins
        win_rate = total_wins / num_trades if num_trades > 0 else 0.0

        update_daily_pnl(
            day=today,
            realized_pnl=realized_pnl,
            num_trades=num_trades,
            win_rate=win_rate,
        )


def _make_team_pair_key(team_a: str, team_b: str) -> str:
    """Create a canonical key from two team names (order-independent)."""
    a = normalize_team_name(team_a)
    b = normalize_team_name(team_b)
    return "|".join(sorted([a, b]))
