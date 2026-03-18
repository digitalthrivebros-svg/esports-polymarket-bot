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
) -> None:
    """Execute a single scan-analyse-trade cycle."""
    logger.info("=== Starting scan cycle ===")

    # 1. Discover markets
    markets: list[EsportsMarket] = scanner.scan_all_esports()
    if not markets:
        logger.info("No esports markets found this cycle")
        return

    # 2. Fetch external odds
    all_odds = odds_client.get_all_esports_odds()

    # 3. Fetch supplementary data (best-effort, non-blocking)
    try:
        cs2_matches = await hltv_client.get_upcoming_matches(days=3)
    except Exception:
        cs2_matches = []
        logger.warning("HLTV fetch failed — continuing without CS2 data")

    # 4. For each market, compute fair odds & edges
    daily = get_daily_pnl()
    daily_pnl = daily.get("realized_pnl", 0.0)
    open_positions = get_open_positions()
    current_exposure = sum(abs(t.get("size", 0)) for t in open_positions)
    concurrent_matches = len({t.get("token_id") for t in open_positions})

    for market in markets:
        # Log the match
        log_match(
            match_id=market.condition_id,
            teams=" vs ".join(market.teams) if market.teams else market.question,
            tournament=market.tournament,
            start_time=market.start_time,
            fmt=market.series_format,
        )

        # Try to find Pinnacle odds for this match (simple name matching)
        game_odds = all_odds.get(market.game, [])

        for token_id, book in market.books.items():
            if book.midpoint <= 0:
                continue

            pm_price = book.midpoint

            # Approach A: if we have Pinnacle odds, compute fair value
            # (In production this would do fuzzy team-name matching)
            fair_prob = pm_price  # fallback: trust PM midpoint
            edge = 0.0

            # Approach B: Glicko model prediction (if teams are known)
            if len(market.teams) == 2:
                model_prob = glicko.predict(
                    market.teams[0], market.teams[1], market.series_format or "BO1"
                )
                # Use Glicko as a secondary signal
                glicko_edge = model_prob - pm_price
                if abs(glicko_edge) > abs(edge):
                    edge = glicko_edge
                    fair_prob = model_prob

            if abs(edge) < 0.001:
                continue

            # Log signal
            signal_id = log_signal(
                match_id=market.condition_id,
                pinnacle_prob=fair_prob,
                pm_price=pm_price,
                edge=edge,
                source="glicko" if abs(edge) > 0 else "pinnacle",
            )

            # 5. Risk check
            if not risk.should_trade(edge, current_exposure, daily_pnl, concurrent_matches):
                logger.debug("Risk check failed for %s (edge=%.4f)", market.condition_id, edge)
                continue

            # 6. Size and execute
            size = risk.position_size(abs(edge), 1000.0)  # TODO: real bankroll
            if size <= 0:
                continue

            side = "BUY" if edge > 0 else "SELL"
            best_price = book.best_ask if side == "BUY" else book.best_bid

            logger.info(
                "SIGNAL: %s | edge=%.4f | size=%.2f | side=%s | token=%s",
                " vs ".join(market.teams) if market.teams else market.condition_id,
                edge, size, side, token_id,
            )

            result = execution.execute_signal(
                token_id=token_id,
                edge=abs(edge),
                size=size,
                side=side,
                best_price=best_price if best_price else None,
            )

            # Log trade
            order_id = ""
            if isinstance(result, dict):
                order_id = result.get("orderID", result.get("order_id", ""))

            log_trade(
                signal_id=signal_id,
                token_id=token_id,
                side=side,
                price=best_price or pm_price,
                size=size,
                order_id=order_id,
                status="sent" if result else "dry_run",
            )

    logger.info("=== Scan cycle complete ===")


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

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)

    logger.info("Bot initialised — scanning every %ds", SCAN_INTERVAL_SECONDS)

    while not _shutdown_event.is_set():
        try:
            await run_cycle(
                scanner, odds_client, hltv_client, valorant_client,
                pandascore_client, glicko, cross_checker, execution, risk,
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
