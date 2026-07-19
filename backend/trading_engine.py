"""Trading engine — evaluates signals through a composable TradingStrategy.

Supports an optional TradingBroker for market data and trade execution.
When a broker is available, use ``evaluate_signal_async()`` instead of
the synchronous ``evaluate_signal()``.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from models import SentimentLevel, TradeAction
from strategy import TradingContext, TradingStrategy
import database
import logging

if TYPE_CHECKING:
    from broker import TradingBroker

logger = logging.getLogger(f"backend.{__name__}")


class TradingEngine:
    """Evaluates sentiment signals against a TradingStrategy to generate trades.

    Accepts a TradingStrategy and optional TradingBroker.  When a broker is
    provided, market data and order execution go through it — the engine
    becomes exchange-agnostic.
    """

    def __init__(
        self,
        database: database.Database,
        strategy: TradingStrategy,
        broker: "TradingBroker | None" = None,
    ):
        self.database = database
        self.strategy = strategy
        self.broker = broker

    def evaluate_signal(
        self,
        sentiment: str,
        confidence_score: float,
        symbol: str,
        news_id: str,
        sentiment_result_id: str,
        price: float = 100.0,
    ) -> Optional[dict]:
        """Build a TradingContext and ask the strategy what to do.

        Returns a trade dict if a trade was created, else None.
        """
        # Build context from what we know
        existing_position = self._get_open_position(symbol)
        ctx = self._build_context(
            symbol=symbol,
            sentiment=sentiment,
            confidence_score=confidence_score,
            price=price,
            existing_position=existing_position,
        )

        logger.info(
            "evaluate_signal: symbol=%s sentiment=%s score=%.2f holding=%s price=%.2f",
            symbol, sentiment, confidence_score, ctx.holding, price,
        )

        # --- Check exits first (if holding) ---
        if ctx.holding and self.strategy.should_sell(ctx):
            self._close_position(existing_position, price)
            logger.info("SELL %s @ %.2f (strategy exit)", symbol, price)
            return None  # no new trade opened

        # --- Check entry ---
        action = None
        if self.strategy.should_buy(ctx):
            action = TradeAction.BUY
        elif self.strategy.should_short(ctx):
            action = TradeAction.SHORT

        if action is None:
            logger.info(
                "evaluate_signal: NO TRADE — strategy rejected  symbol=%s  "
                "should_buy=%s  should_short=%s  entry_rules=%s",
                symbol,
                self.strategy.should_buy(ctx),
                self.strategy.should_short(ctx),
                [type(r).__name__ for r in self.strategy.entry_rules],
            )
            return None

        # --- Position size ---
        position_size = self.strategy.get_position_size(ctx)

        trade = {
            "id": str(uuid.uuid4()),
            "news_id": news_id,
            "sentiment_result_id": sentiment_result_id,
            "action": action.value,
            "symbol": symbol,
            "entry_price": price,
            "status": "OPEN",
            "pnl": 0.0,
            "position_size": position_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "closed_at": None,
        }
        self.database.insert_trade(trade)
        logger.info(
            "%s %s @ %.2f size=%.0f (strategy: %s)",
            action.value, symbol, price, position_size,
            type(self.strategy).__name__,
        )
        return trade

    # ── async broker-driven evaluation ────────────────────

    async def evaluate_signal_async(
        self,
        sentiment: str,
        confidence_score: float,
        symbol: str,
        exchange: str = "AU",
        news_id: str = "",
        sentiment_result_id: str = "",
    ) -> Optional[dict]:
        """Async variant — uses TradingBroker for real prices and positions.

        Falls back to synchronous evaluate_signal if no broker is configured.
        """
        if self.broker is None:
            return self.evaluate_signal(
                sentiment, confidence_score, symbol,
                news_id, sentiment_result_id,
            )

        # Get live price from broker
        try:
            quote = await self.broker.get_quote(symbol, exchange)
            price = quote.last_price
        except Exception as e:
            logger.warning("Broker quote failed for %s: %s — using fallback", symbol, e)
            price = 100.0

        # Get current position from broker
        try:
            position = await self.broker.get_position(symbol)
        except Exception:
            position = None

        # Get account
        try:
            account = await self.broker.get_account()
            available_cash = account.cash
        except Exception:
            available_cash = self.database.get_config_float("available_cash", 10000.0)

        # Build context
        holding = position is not None and position.quantity > 0
        ctx = TradingContext(
            now=datetime.now(timezone.utc),
            symbol=symbol,
            sentiment_score=confidence_score,
            sentiment_label=sentiment,
            price=price,
            entry_price=position.avg_cost if holding else None,
            holding=holding,
            holding_days=0,  # broker doesn't track days — could be added later
            position_size=position.market_value if holding else 0.0,
            available_cash=available_cash,
        )

        logger.debug(
            "evaluate_signal_async: symbol=%s sentiment=%s score=%.2f holding=%s price=%.2f",
            symbol, sentiment, confidence_score, ctx.holding, price,
        )

        # Check exits
        if ctx.holding and self.strategy.should_sell(ctx):
            from domain import OrderRequest, OrderSide, OrderType as DomainOrderType
            sell_req = OrderRequest(
                exchange=exchange,
                symbol=symbol.upper(),
                side=OrderSide.SELL,
                quantity=position.quantity,
                order_type=DomainOrderType.MARKET,
            )
            try:
                await self.broker.submit_order(sell_req)
                logger.info("SELL %s @ %.2f (broker, strategy exit)", symbol, price)
            except Exception as e:
                logger.error("Broker sell failed: %s", e)
            return None

        # Check entry
        if not self.strategy.should_buy(ctx):
            return None

        position_size = self.strategy.get_position_size(ctx)
        shares = int(position_size / price) if price > 0 else 0
        if shares == 0:
            return None

        from domain import OrderRequest, OrderSide, OrderType as DomainOrderType
        buy_req = OrderRequest(
            exchange=exchange,
            symbol=symbol.upper(),
            side=OrderSide.BUY,
            quantity=shares,
            order_type=DomainOrderType.MARKET,
        )
        try:
            order = await self.broker.submit_order(buy_req)
            logger.info(
                "BUY %s @ %.2f x%d (broker, strategy: %s)",
                symbol, order.avg_fill_price or price, shares,
                type(self.strategy).__name__,
            )
            return {
                "id": order.order_id,
                "news_id": news_id,
                "sentiment_result_id": sentiment_result_id,
                "action": "BUY",
                "symbol": symbol,
                "entry_price": order.avg_fill_price or price,
                "status": "OPEN",
                "pnl": 0.0,
                "position_size": position_size,
                "created_at": order.created_at.isoformat(),
                "closed_at": None,
            }
        except Exception as e:
            logger.error("Broker buy failed: %s", e)
            return None

    # ── helpers ───────────────────────────────────────────

    def _build_context(
        self,
        symbol: str,
        sentiment: str,
        confidence_score: float,
        price: float,
        existing_position: dict | None,
    ) -> TradingContext:
        """Construct a TradingContext from the signal and current state."""
        holding = existing_position is not None
        entry_price = existing_position.get("entry_price") if existing_position else None

        # Calculate holding days
        holding_days = 0
        if existing_position and existing_position.get("created_at"):
            try:
                created = datetime.fromisoformat(
                    existing_position["created_at"].replace("Z", "+00:00")
                )
                holding_days = (datetime.now(timezone.utc) - created).days
            except (ValueError, TypeError):
                pass

        # Get available cash from config
        available_cash = self.database.get_config_float("available_cash", 10000.0)

        return TradingContext(
            now=datetime.now(timezone.utc),
            symbol=symbol,
            sentiment_score=confidence_score,
            sentiment_label=sentiment,
            price=price,
            entry_price=entry_price,
            holding=holding,
            holding_days=holding_days,
            position_size=existing_position.get("position_size", 0.0) if existing_position else 0.0,
            available_cash=available_cash,
        )

    def _get_open_position(self, symbol: str) -> dict | None:
        """Return the open position for symbol, or None."""
        positions = self.database.get_positions()
        for p in positions:
            if p.get("symbol") == symbol and p.get("status") == "OPEN":
                return p
        return None

    def _close_position(self, position: dict, exit_price: float):
        """Mark a position as CLOSED and record realized PnL."""
        entry_price = position.get("entry_price", exit_price)
        pnl = exit_price - entry_price
        self.database.close_trade(
            trade_id=position["id"],
            exit_price=exit_price,
            pnl=round(pnl, 4),
            closed_at=datetime.now(timezone.utc).isoformat(),
        )

    # ── read-only queries (unchanged API) ─────────────────

    def get_positions(self) -> list[dict]:
        """Return all currently open positions."""
        return self.database.get_positions()

    def get_trade_history(self, limit: int = 50) -> list[dict]:
        """Return recent trade history."""
        return self.database.get_trade_history(limit)

    def get_pnl_summary(self) -> dict:
        """Return a simple P&L summary."""
        positions = self.database.get_positions()
        history = self.database.get_trade_history(1000)
        unrealized = sum(p.get("pnl", 0.0) for p in positions)
        realized = sum(t.get("pnl", 0.0) for t in history if t.get("status") == "CLOSED")
        return {
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_pnl": unrealized + realized,
            "open_positions": len(positions),
            "total_trades": len(history),
        }
