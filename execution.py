"""Module 4: Order placement via the Polymarket CLOB API (py-clob-client)."""

import logging
from typing import Any

from config import (
    POLYMARKET_PRIVATE_KEY,
    CLOB_API_BASE,
    POLYGON_CHAIN_ID,
    DRY_RUN,
)

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Places, cancels, and manages orders on Polymarket's CLOB.

    Uses the py-clob-client SDK for authenticated trading endpoints.
    When DRY_RUN is True, orders are only logged, not sent.
    """

    def __init__(self) -> None:
        self.dry_run = DRY_RUN
        self._client: Any = None
        self._creds: Any = None

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        """Lazy-initialise the ClobClient (requires the private key)."""
        if self._client is not None:
            return self._client

        if not POLYMARKET_PRIVATE_KEY:
            raise RuntimeError(
                "POLYMARKET_PRIVATE_KEY is not set — cannot initialise CLOB client"
            )

        try:
            from py_clob_client.client import ClobClient  # type: ignore[import-untyped]

            self._client = ClobClient(
                host=CLOB_API_BASE,
                key=POLYMARKET_PRIVATE_KEY,
                chain_id=POLYGON_CHAIN_ID,
            )
        except ImportError:
            raise RuntimeError(
                "py-clob-client is not installed. Run: pip install py-clob-client"
            )
        return self._client

    def create_api_credentials(self) -> Any:
        """One-time L2 credential generation (EIP-712 signature)."""
        client = self._ensure_client()
        self._creds = client.create_api_creds()
        client.set_api_creds(self._creds)
        logger.info("API credentials created successfully")
        return self._creds

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def place_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
    ) -> dict[str, Any] | None:
        """Post a GTC limit order.

        Args:
            token_id: The outcome token to trade.
            price: Limit price (0–1 range).
            size: Amount in USDC.
            side: "BUY" or "SELL".

        Returns:
            Order response dict, or None in dry-run mode.
        """
        logger.info(
            "LIMIT %s %s @ %.4f size=%.2f (token=%s)",
            side, "BUY" if side == "BUY" else "SELL", price, size, token_id,
        )
        if self.dry_run:
            logger.info("[DRY RUN] Order not sent")
            return None

        client = self._ensure_client()
        try:
            from py_clob_client.order_builder.constants import BUY, SELL  # type: ignore[import-untyped]

            order_side = BUY if side.upper() == "BUY" else SELL
            order = client.create_and_post_order(
                {
                    "tokenID": token_id,
                    "price": price,
                    "size": size,
                    "side": order_side,
                }
            )
            logger.info("Order placed: %s", order)
            return order  # type: ignore[return-value]
        except Exception:
            logger.exception("Failed to place limit order")
            return None

    def place_market_order(
        self,
        token_id: str,
        size: float,
        side: str = "BUY",
    ) -> dict[str, Any] | None:
        """Take the current best offer (market order via aggressive limit).

        Polymarket's CLOB does not have a native market-order type, so we
        place an aggressive limit order at 0.99 (buy) or 0.01 (sell).
        """
        aggressive_price = 0.99 if side.upper() == "BUY" else 0.01
        logger.info(
            "MARKET %s size=%.2f (aggressive limit @ %.2f, token=%s)",
            side, size, aggressive_price, token_id,
        )
        return self.place_limit_order(token_id, aggressive_price, size, side)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order by ID."""
        logger.info("Cancelling order %s", order_id)
        if self.dry_run:
            logger.info("[DRY RUN] Cancel not sent")
            return True

        client = self._ensure_client()
        try:
            client.cancel(order_id)
            logger.info("Order %s cancelled", order_id)
            return True
        except Exception:
            logger.exception("Failed to cancel order %s", order_id)
            return False

    def cancel_all_orders(self) -> bool:
        """Cancel every open order."""
        logger.info("Cancelling all open orders")
        if self.dry_run:
            logger.info("[DRY RUN] Cancel-all not sent")
            return True

        client = self._ensure_client()
        try:
            client.cancel_all()
            logger.info("All orders cancelled")
            return True
        except Exception:
            logger.exception("Failed to cancel all orders")
            return False

    def get_open_orders(self, condition_id: str) -> list[dict[str, Any]]:
        """Retrieve open orders for a given condition/market."""
        if self.dry_run:
            return []

        client = self._ensure_client()
        try:
            orders = client.get_orders(market=condition_id)
            return orders if isinstance(orders, list) else []
        except Exception:
            logger.exception("Failed to fetch open orders for %s", condition_id)
            return []

    def get_fee_rate(self) -> float | None:
        """Return the current fee rate from the CLOB."""
        if self.dry_run:
            return None

        client = self._ensure_client()
        try:
            rate = client.get_fee_rate()
            return float(rate) if rate is not None else None
        except Exception:
            logger.exception("Failed to fetch fee rate")
            return None

    # ------------------------------------------------------------------
    # Execution logic
    # ------------------------------------------------------------------

    def execute_signal(
        self,
        token_id: str,
        edge: float,
        size: float,
        side: str = "BUY",
        best_price: float | None = None,
    ) -> dict[str, Any] | None:
        """Decide between market and limit order based on edge magnitude.

        - Edge > 5c  → market order (take best offer)
        - Edge 3–5c  → limit order 1–2c inside best price
        """
        if edge > 0.05:
            return self.place_market_order(token_id, size, side)
        elif best_price is not None:
            # Place limit 1–2c inside the best price
            offset = 0.01 if edge < 0.04 else 0.02
            if side.upper() == "BUY":
                limit_price = best_price + offset
            else:
                limit_price = best_price - offset
            limit_price = max(0.01, min(0.99, limit_price))
            return self.place_limit_order(token_id, limit_price, size, side)
        else:
            return self.place_market_order(token_id, size, side)
