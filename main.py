"""Main scheduler — ties all modules together in an async loop."""

import asyncio
import logging
import signal
import sys
from datetime import date
from typing import Any

from config import (
    SCAN_INTERVAL_SECONDS,
    DRY_RUN,
    PAPER_BANKROLL,
    configure_logging,
)
from db import init_db, log_signal, log_trade, get_daily_pnl, log_match, get_open_positions
from scanner import PolymarketScanner, EsportsMarket
from data_ingest.odds_client import OddsClient
from data_ingest.hltv_client import HLTVClient
from data_ingest.valorant_client import ValorantClient
from data_ingest.pandascore import PandaScoreClient
from pricing.odds_arb import compute_fair_odds, compute_edge
from pricing.elo_model import GlickoModel
from pricing.cross_market import CrossMarketChecker
from execution import ExecutionEngine
from risk import RiskManager
from paper_trader import PaperTrader
from resolver import MatchResolver
from matching import match_pinnacle_to_polymarket

logger = logging.getLogger(__name__)

# ── Graceful shutdown ────────────────────────────────────────────────
_shutdown_event = asyncio.Event()


def _handle_signal(sig: int, _frame: Any) -> None:
    logger.info("Received signal %s — shutting down gracefully…", sig)
    _shutdown_event.set()


# ── Main loop ────────────────────────────────────────────────────────

async def run_cycle(
    scanner: PolymarketScanner,
    odds_client: OddsClient,
    hltv_client: HLTVClient,
    valorant_client: ValorantClient,
    pandascore_client: PandaScoreClient,
    glicko: GlickoModel,
    cross_checker: CrossMarketChecker,
    execution: ExecutionEngine,
    risk: RiskManager,
    paper_trader: PaperTrader,
    resolver: MatchResolver,
) -> None:
    """Execute a single scan-analyse-trade cycle."""
    logger.info("=== Starting scan cycle ===")

    # 1. Resolve completed matches first (settle paper trades)
    try:
        settlements = resolver.resolve_completed_matches()
        if settlements:
            logger.info("Settled %d trade(s) this cycle", len(settlements))
    except Exception:
        logger.exception("Match resolution failed — continuing")

    # 2. Discover Polymarket markets
    markets: list[EsportsMarket] = scanner.scan_all_esports()
    if not markets:
        logger.info("No esports markets found this cycle")
        _log_portfolio_summary(paper_trader)
        return

    # 3. Fetch Pinnacle odds (cached)
    all_odds = odds_client.get_all_esports_odds()

    # 4. Fetch PandaScore upcoming matches (for team name bridge)
    pandascore_upcoming = pandascore_client.get_all_upcoming_matches()

    # 5. Fetch supplementary data (best-effort, non-blocking)
    try:
        cs2_matches = await hltv_client.get_upcoming_matches(days=3)
    except Exception:
        cs2_matches = []
        logger.warning("HLTV fetch failed — continuing without CS2 data")

    # 6. Fuzzy match Pinnacle to Polymarket
    matched_pairs = match_pinnacle_to_polymarket(all_odds, markets, pandascore_upcoming)

    # 7. For each market, compute fair odds & edges
    daily = get_daily_pnl()
    daily_pnl = daily.get("realized_pnl", 0.0)
    open_positions = get_open_positions()
    current_exposure = sum(abs(t.get("size", 0)) for t in open_positions)
    concurrent_matches = len({t.get("token_id") for t in open_positions})

    # Build a lookup for matched pairs by condition_id
    matched_by_condition: dict[str, Any] = {}
    for mp in matched_pairs:
        matched_by_condition[mp.polymarket_market.condition_id] = mp

    for market in markets:
        teams_str = " vs ".join(market.teams) if market.teams else market.question

        # Log the match
        log_match(
            match_id=market.condition_id,
            teams=teams_str,
            tournament=market.tournament,
            start_time=market.start_time,
            fmt=market.series_format,
        )

        mp = matched_by_condition.get(market.condition_id)

        for token_id, book in market.books.items():
            if book.midpoint <= 0:
                continue

            pm_price = book.midpoint
            fair_prob = pm_price  # fallback: trust PM midpoint
            edge = 0.0
            source = "none"
            team_backed = ""

            # Approach A: Pinnacle fair value from matched pair
            if mp is not None:
                pinnacle_fair_a, pinnacle_fair_b = compute_fair_odds(
                    mp.pinnacle_odds_a, mp.pinnacle_odds_b
                )
                # Determine which team this token corresponds to
                # Use the first token for team A, second for team B
                token_ids = list(market.token_ids.values())
                if len(token_ids) >= 2:
                    if token_id == token_ids[0]:
                        pinnacle_fair = pinnacle_fair_a
                        team_backed = mp.team_a
                    else:
                        pinnacle_fair = pinnacle_fair_b
                        team_backed = mp.team_b

                    pinnacle_edge = pinnacle_fair - pm_price
                    if abs(pinnacle_edge) > abs(edge):
                        edge = pinnacle_edge
                        fair_prob = pinnacle_fair
                        source = "pinnacle"

            # Approach B: Glicko model prediction (if teams are known)
            if len(market.teams) == 2:
                model_prob = glicko.predict(
                    market.teams[0], market.teams[1], market.series_format or "BO1"
                )
                glicko_edge = model_prob - pm_price
                if abs(glicko_edge) > abs(edge):
                    edge = glicko_edge
                    fair_prob = model_prob
                    source = "glicko"
                    # Set team_backed based on edge direction
                    if not team_backed:
                        team_backed = market.teams[0] if edge > 0 else market.teams[1]

            if abs(edge) < 0.001:
                continue

            # Log signal
            signal_id = log_signal(
                match_id=market.condition_id,
                pinnacle_prob=fair_prob,
                pm_price=pm_price,
                edge=edge,
                source=source,
            )

            # Risk check
            if not risk.should_trade(edge, current_exposure, daily_pnl, concurrent_matches):
                logger.debug("Risk check failed for %s (edge=%.4f)", market.condition_id, edge)
                continue

            # Size position using paper trader bankroll
            size = risk.position_size(abs(edge), paper_trader.bankroll)
            if size <= 0:
                continue

            side = "BUY" if edge > 0 else "SELL"
            best_price = book.best_ask if side == "BUY" else book.best_bid
            entry_price = best_price if best_price else pm_price

            logger.info(
                "SIGNAL: %s | edge=%.4f | size=%.2f | side=%s | source=%s | token=%s",
                teams_str, edge, size, side, source, token_id,
            )

            # Paper trade execution (DRY_RUN mode)
            if DRY_RUN:
                match_id = mp.match_id if mp else market.condition_id
                paper_trader.execute_paper_trade(
                    token_id=token_id,
                    side=side,
                    price=entry_price,
                    size=size,
                    match_id=match_id,
                    teams=teams_str,
                    team_backed=team_backed or (market.teams[0] if market.teams else ""),
                    edge=edge,
                    signal_id=signal_id,
                )
            else:
                result = execution.execute_signal(
                    token_id=token_id,
                    edge=abs(edge),
                    size=size,
                    side=side,
                    best_price=best_price if best_price else None,
                )
                order_id = ""
                if isinstance(result, dict):
                    order_id = result.get("orderID", result.get("order_id", ""))

                log_trade(
                    signal_id=signal_id,
                    token_id=token_id,
                    side=side,
                    price=entry_price,
                    size=size,
                    order_id=order_id,
                    status="sent" if result else "dry_run",
                    match_id=market.condition_id,
                    teams=teams_str,
                    team_backed=team_backed,
                )

    # End-of-cycle portfolio summary
    _log_portfolio_summary(paper_trader)
    logger.info("=== Scan cycle complete ===")


def _log_portfolio_summary(paper_trader: PaperTrader) -> None:
    """Log portfolio summary at end of cycle."""
    summary = paper_trader.get_summary()
    logger.info(
        "PORTFOLIO: bankroll=$%.2f | open=%d | settled=%d | "
        "total_pnl=$%.2f | win_rate=%.1f%% | roi=%.1f%%",
        summary["bankroll"], summary["open_count"], summary["settled_count"],
        summary["total_pnl"], summary["win_rate"] * 100, summary["roi"] * 100,
    )


async def main() -> None:
    """Entry point — initialise components and run the scan loop."""
    configure_logging()
    logger.info("Esports Polymarket Bot starting (DRY_RUN=%s)", DRY_RUN)

    init_db()

    scanner = PolymarketScanner()
    odds_client = OddsClient()
    hltv_client = HLTVClient()
    valorant_client = ValorantClient()
    pandascore_client = PandaScoreClient()
    glicko = GlickoModel()
    cross_checker = CrossMarketChecker()
    execution = ExecutionEngine()
    risk = RiskManager()
    paper_trader = PaperTrader(initial_bankroll=PAPER_BANKROLL)
    resolver = MatchResolver(pandascore=pandascore_client, paper_trader=paper_trader)

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    logger.info(
        "Bot initialised — scanning every %ds | paper_bankroll=$%.2f",
        SCAN_INTERVAL_SECONDS, PAPER_BANKROLL,
    )

    while not _shutdown_event.is_set():
        try:
            await run_cycle(
                scanner, odds_client, hltv_client, valorant_client,
                pandascore_client, glicko, cross_checker, execution, risk,
                paper_trader, resolver,
            )
        except Exception:
            logger.exception("Scan cycle failed — will retry next interval")

        # Wait for next cycle or shutdown
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(), timeout=SCAN_INTERVAL_SECONDS
            )
        except asyncio.TimeoutError:
            pass  # timeout = time for next cycle

    logger.info("Bot shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
