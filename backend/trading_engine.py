"""Mock trading engine — evaluates sentiment signals and simulates trades."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from models import SentimentLevel, TradeAction
import database


class MockTradingEngine:
    """Simulates buy/short trades based on sentiment signals."""

    def evaluate_signal(
        self, sentiment: str, symbol: str, news_id: str, sentiment_result_id: str
    ) -> Optional[dict]:
        """
        Evaluate a sentiment signal and create a trade if applicable.
        - 超级利好 → BUY
        - 超级利空 → SHORT
        - All others → no trade
        Returns the trade dict if created, else None.
        """
        if sentiment == SentimentLevel.SUPER_BULLISH.value:
            action = TradeAction.BUY
        elif sentiment == SentimentLevel.SUPER_BEARISH.value:
            action = TradeAction.SHORT
        else:
            return None

        trade = {
            "id": str(uuid.uuid4()),
            "news_id": news_id,
            "sentiment_result_id": sentiment_result_id,
            "action": action.value,
            "symbol": symbol,
            "entry_price": 100.0,  # mock price
            "status": "OPEN",
            "pnl": 0.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "closed_at": None,
        }
        database.insert_trade(trade)
        return trade

    def get_positions(self) -> list[dict]:
        """Return all currently open positions."""
        return database.get_positions()

    def get_trade_history(self, limit: int = 50) -> list[dict]:
        """Return recent trade history."""
        return database.get_trade_history(limit)

    def get_pnl_summary(self) -> dict:
        """Return a simple P&L summary."""
        positions = database.get_positions()
        history = database.get_trade_history(1000)
        unrealized = sum(p.get("pnl", 0.0) for p in positions)
        realized = sum(t.get("pnl", 0.0) for t in history if t.get("status") == "CLOSED")
        return {
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_pnl": unrealized + realized,
            "open_positions": len(positions),
            "total_trades": len(history),
        }
