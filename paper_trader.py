"""Paper trading engine — simulates order fills and tracks virtual positions with P&L."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import PAPER_BANKROLL
from db import get_unsettled_trades, update_trade, log_trade

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    """A single paper trade position."""

    trade_id: int
    match_id: str
    token_id: str
    teams: str  # "Team A vs Team B"
    side: str  # BUY or SELL
    entry_price: float
    size: float  # USDC amount
    team_backed: str  # which team we're betting on
    timestamp: str
    status: str = "open"  # open, won, lost, settled
    pnl: float = 0.0


class PaperTrader:
    """Simulates order fills and tracks virtual positions."""

    def __init__(self, initial_bankroll: float = PAPER_BANKROLL) -> None:
        self.initial_bankroll = initial_bankroll
        self.bankroll = initial_bankroll
        self.positions: list[PaperPosition] = []
        self._load_existing_positions()

    def _load_existing_positions(self) -> None:
        """Load any open positions from the database on init."""
        open_trades = get_unsettled_trades()
        for t in open_trades:
            if t.get("status") in ("open", "filled", "pending"):
                self.positions.append(
                    PaperPosition(
                        trade_id=t["trade_id"],
                        match_id=t.get("match_id", ""),
                        token_id=t["token_id"],
                        teams=t.get("teams", ""),
                        side=t["side"],
                        entry_price=t["price"],
                        size=t["size"],
                        team_backed=t.get("team_backed", ""),
                        timestamp=t.get("created_at", ""),
                        status="open",
                    )
                )
                # Deduct from bankroll for existing open positions
                self.bankroll -= t["size"]

        if self.positions:
            logger.info("Loaded %d open paper positions (bankroll=%.2f)", len(self.positions), self.bankroll)

    def execute_paper_trade(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        match_id: str,
        teams: str,
        team_backed: str,
        edge: float,
        signal_id: int | None = None,
    ) -> dict[str, Any]:
        """Simulate a fill at the current price.

        Args:
            token_id: Polymarket token being traded.
            side: BUY or SELL.
            price: Entry price (0-1).
            size: USDC amount to wager.
            match_id: Unique match identifier for settlement.
            teams: "Team A vs Team B" display string.
            team_backed: Which team this trade backs.
            edge: Computed edge for logging.
            signal_id: Optional signal ID for DB linking.

        Returns:
            Dict with trade details for logging.
        """
        if size > self.bankroll:
            logger.warning(
                "Insufficient bankroll (%.2f) for trade size %.2f — reducing",
                self.bankroll, size,
            )
            size = self.bankroll
            if size <= 0:
                return {"status": "rejected", "reason": "no_bankroll"}

        # Simulate fill at the given price
        # For BUY: cost = size (USDC), shares = size / price
        # For SELL: cost = size (USDC), shares = size / (1 - price)
        shares = size / price if side == "BUY" else size / (1 - price)

        # Record in DB
        trade_id = log_trade(
            signal_id=signal_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            order_id="paper",
            status="open",
            match_id=match_id,
            teams=teams,
            team_backed=team_backed,
        )

        # Track position in memory
        now = datetime.now(timezone.utc).isoformat()
        position = PaperPosition(
            trade_id=trade_id,
            match_id=match_id,
            token_id=token_id,
            teams=teams,
            side=side,
            entry_price=price,
            size=size,
            team_backed=team_backed,
            timestamp=now,
        )
        self.positions.append(position)
        self.bankroll -= size

        logger.info(
            "PAPER TRADE: %s %s @ %.4f size=$%.2f | %s backs %s | edge=%.4f | bankroll=$%.2f",
            side, token_id[:12], price, size, teams, team_backed, edge, self.bankroll,
        )

        return {
            "trade_id": trade_id,
            "token_id": token_id,
            "side": side,
            "price": price,
            "size": size,
            "shares": round(shares, 4),
            "match_id": match_id,
            "teams": teams,
            "team_backed": team_backed,
            "edge": edge,
            "status": "open",
        }

    def settle_match(self, match_id: str, winner_team: str) -> list[dict[str, Any]]:
        """Settle all open positions for a completed match.

        Args:
            match_id: The match that has completed.
            winner_team: Name of the winning team.

        Returns:
            List of settlement result dicts.
        """
        settlements: list[dict[str, Any]] = []

        for pos in self.positions:
            if pos.match_id != match_id or pos.status != "open":
                continue

            won = normalize_for_compare(pos.team_backed) == normalize_for_compare(winner_team)

            if pos.side == "BUY":
                shares = pos.size / pos.entry_price
                if won:
                    # Shares pay out $1 each
                    payout = shares * 1.0
                    pnl = payout - pos.size
                    settlement_price = 1.0
                else:
                    payout = 0.0
                    pnl = -pos.size
                    settlement_price = 0.0
            else:  # SELL
                shares = pos.size / (1 - pos.entry_price)
                if won:
                    # We sold — if the team we backed wins, we lose on SELL
                    # Actually SELL means we bet AGAINST; if team_backed wins, SELL loses
                    payout = 0.0
                    pnl = -pos.size
                    settlement_price = 1.0
                else:
                    payout = shares * 1.0
                    pnl = payout - pos.size
                    settlement_price = 0.0

            pos.status = "won" if pnl > 0 else "lost"
            pos.pnl = pnl
            self.bankroll += pos.size + pnl  # Return cost + profit (or cost - loss)

            # Update DB
            update_trade(
                pos.trade_id,
                status=pos.status,
                pnl=round(pnl, 4),
                fill_price=pos.entry_price,
                settlement_price=settlement_price,
            )

            settlements.append({
                "trade_id": pos.trade_id,
                "match_id": match_id,
                "teams": pos.teams,
                "team_backed": pos.team_backed,
                "winner": winner_team,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "settlement_price": settlement_price,
                "size": pos.size,
                "pnl": round(pnl, 4),
                "result": pos.status,
            })

            logger.info(
                "SETTLED: %s | backed=%s | winner=%s | pnl=$%.2f | %s",
                pos.teams, pos.team_backed, winner_team, pnl, pos.status.upper(),
            )

        return settlements

    def get_summary(self) -> dict[str, Any]:
        """Return portfolio summary stats."""
        open_positions = [p for p in self.positions if p.status == "open"]
        settled = [p for p in self.positions if p.status in ("won", "lost")]
        total_pnl = sum(p.pnl for p in settled)
        wins = sum(1 for p in settled if p.status == "won")
        win_rate = wins / len(settled) if settled else 0.0
        roi = total_pnl / self.initial_bankroll if self.initial_bankroll else 0.0

        return {
            "bankroll": round(self.bankroll, 2),
            "initial_bankroll": self.initial_bankroll,
            "open_count": len(open_positions),
            "settled_count": len(settled),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "roi": round(roi, 4),
            "wins": wins,
            "losses": len(settled) - wins,
        }


def normalize_for_compare(name: str) -> str:
    """Lowercase and strip common suffixes for team comparison."""
    import re
    name = name.strip().lower()
    name = re.sub(r"\s*(esports|gaming|team|club|gg)\s*$", "", name, flags=re.IGNORECASE).strip()
    return name
