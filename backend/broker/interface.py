"""TradingBroker — the single interface to any exchange / broker.

Every adapter (GrpcBroker, IBKRBroker, PaperBroker, …) implements this ABC.
Strategy code depends ONLY on this interface — never on a concrete adapter.
"""

from abc import ABC, abstractmethod

from domain import (
    OrderRequest,
    Order,
    Trade,
    Position,
    Account,
    Quote,
    OrderStatus,
)


class TradingBroker(ABC):
    """Abstract broker / exchange gateway.

    All methods are async — real brokers involve I/O.
    """

    # ── Market Data ──────────────────────────────────────

    @abstractmethod
    async def get_quote(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> Quote:
        """Fetch a real-time quote for *symbol*."""
        ...

    # ── Trading ──────────────────────────────────────────

    @abstractmethod
    async def submit_order(
        self,
        order: OrderRequest,
    ) -> Order:
        """Submit a new order.  Returns the broker-confirmed Order."""
        ...

    @abstractmethod
    async def cancel_order(
        self,
        order_id: str,
    ) -> Order:
        """Cancel an open order by ID.  Returns the updated Order."""
        ...

    # ── Orders ───────────────────────────────────────────

    @abstractmethod
    async def get_order(
        self,
        order_id: str,
    ) -> Order:
        """Look up a single order by ID."""
        ...

    @abstractmethod
    async def list_orders(
        self,
        symbol: str | None = None,
        status: OrderStatus | None = None,
    ) -> list[Order]:
        """List orders, optionally filtered."""
        ...

    # ── Trades ───────────────────────────────────────────

    @abstractmethod
    async def get_trade(
        self,
        trade_id: str,
    ) -> Trade:
        """Look up a single trade (fill) by ID."""
        ...

    @abstractmethod
    async def list_trades(
        self,
        symbol: str | None = None,
    ) -> list[Trade]:
        """List executed trades, optionally filtered by symbol."""
        ...

    # ── Portfolio ────────────────────────────────────────

    @abstractmethod
    async def get_position(
        self,
        symbol: str,
    ) -> Position | None:
        """Return the current position for *symbol*, or None."""
        ...

    @abstractmethod
    async def list_positions(self) -> list[Position]:
        """Return all open positions."""
        ...

    @abstractmethod
    async def get_account(self) -> Account:
        """Return current account / portfolio summary."""
        ...
