"""GrpcBroker — gRPC client adapter for book_trading_simulator.

Talks to the gRPC server defined by book_trading_simulator/proto/trading/trading.proto.
Maps proto messages ↔ domain models.
"""

import sys, os
from datetime import datetime, timezone

# Make generated stubs importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "grpc_stubs"))

import grpc
import trading_pb2 as pb
import trading_pb2_grpc as pb_grpc

from .interface import TradingBroker
from domain import (
    OrderRequest, Order, Trade, Position, Account, Quote,
    OrderSide, OrderType, OrderStatus,
)

# ═══════════════════════════════════════════════════════════════
# Enum mappings
# ═══════════════════════════════════════════════════════════════

_SIDE_TO_PROTO = {
    OrderSide.BUY: pb.BUY,
    OrderSide.SELL: pb.SELL,
}
_SIDE_FROM_PROTO = {pb.BUY: OrderSide.BUY, pb.SELL: OrderSide.SELL}

_ORDER_TYPE_TO_PROTO = {
    OrderType.MARKET: pb.MARKET,
    OrderType.LIMIT: pb.LIMIT,
}
_ORDER_TYPE_FROM_PROTO = {pb.MARKET: OrderType.MARKET, pb.LIMIT: OrderType.LIMIT}

_STATUS_FROM_PROTO = {
    pb.PENDING: OrderStatus.NEW,
    pb.FILLED: OrderStatus.FILLED,
    pb.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
    pb.REJECTED: OrderStatus.REJECTED,
    pb.CANCELLED: OrderStatus.CANCELLED,
}


def _ts_to_dt(ts) -> datetime:
    """protobuf Timestamp → datetime."""
    return ts.ToDatetime().replace(tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════

class GrpcBroker(TradingBroker):
    """gRPC adapter — calls book_trading_simulator's gRPC server.

    Usage::

        broker = GrpcBroker("localhost:50051")
        quote = await broker.get_quote("AAPL", exchange="US")
    """

    def __init__(self, host: str = "localhost:50051"):
        self._host = host
        self._channel: grpc.aio.Channel | None = None
        self._stub: pb_grpc.TradingServiceStub | None = None

    async def _ensure_connected(self):
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._host)
            self._stub = pb_grpc.TradingServiceStub(self._channel)

    @property
    def stub(self) -> pb_grpc.TradingServiceStub:
        if self._stub is None:
            raise RuntimeError("GrpcBroker not connected. Call await broker._ensure_connected() first.")
        return self._stub

    async def close(self):
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None

    # ── Market Data ──────────────────────────────────────

    async def get_quote(self, symbol: str, exchange: str | None = None) -> Quote:
        await self._ensure_connected()
        req = pb.GetQuoteRequest(
            exchange=exchange or "AU",
            symbol=symbol.upper(),
        )
        resp = await self.stub.GetQuote(req)
        return Quote(
            exchange=resp.exchange,
            symbol=resp.symbol,
            last_price=resp.current_price,
            open_price=resp.open_price,
            high_price=resp.high_price,
            low_price=resp.low_price,
            previous_close=resp.previous_close,
            volume=resp.volume,
            timestamp=_ts_to_dt(resp.timestamp),
        )

    # ── Trading ──────────────────────────────────────────

    async def submit_order(self, order: OrderRequest) -> Order:
        await self._ensure_connected()
        side = _SIDE_TO_PROTO.get(order.side, pb.BUY)
        otype = _ORDER_TYPE_TO_PROTO.get(order.order_type, pb.MARKET)

        if order.side == OrderSide.BUY:
            req = pb.BuyStockRequest(
                exchange=order.exchange,
                symbol=order.symbol.upper(),
                quantity=order.quantity,
                price=order.price or 0.0,
                order_type=otype,
            )
            resp = await self.stub.BuyStock(req)
        else:
            req = pb.SellStockRequest(
                exchange=order.exchange,
                symbol=order.symbol.upper(),
                quantity=order.quantity,
                price=order.price or 0.0,
                order_type=otype,
            )
            resp = await self.stub.SellStock(req)

        return _trade_response_to_order(resp)

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError("cancel_order not yet implemented in proto")

    # ── Orders ───────────────────────────────────────────

    async def get_order(self, order_id: str) -> Order:
        raise NotImplementedError("get_order not yet implemented in proto")

    async def list_orders(
        self, symbol: str | None = None, status: OrderStatus | None = None
    ) -> list[Order]:
        raise NotImplementedError("list_orders not yet implemented in proto")

    # ── Trades ───────────────────────────────────────────

    async def get_trade(self, trade_id: str) -> Trade:
        raise NotImplementedError("get_trade not yet implemented in proto")

    async def list_trades(self, symbol: str | None = None) -> list[Trade]:
        raise NotImplementedError("list_trades not yet implemented in proto")

    # ── Portfolio ────────────────────────────────────────

    async def get_position(self, symbol: str) -> Position | None:
        await self._ensure_connected()
        resp = await self.stub.ViewPortfolio(pb.ViewPortfolioRequest(exchange=""))
        for h in resp.holdings:
            if h.symbol.upper() == symbol.upper():
                return _proto_holding_to_position(h)
        return None

    async def list_positions(self) -> list[Position]:
        await self._ensure_connected()
        resp = await self.stub.ViewPortfolio(pb.ViewPortfolioRequest(exchange=""))
        return [_proto_holding_to_position(h) for h in resp.holdings]

    async def get_account(self) -> Account:
        await self._ensure_connected()
        resp = await self.stub.ViewPortfolio(pb.ViewPortfolioRequest(exchange=""))
        return Account(
            cash=resp.cash,
            market_value=resp.total_holdings_value,
            total_asset=resp.total_portfolio_value,
            unrealized_pnl=resp.total_unrealized_pnl,
            initial_fund=resp.initial_fund,
        )


# ═══════════════════════════════════════════════════════════════
# Proto ↔ Domain mappers
# ═══════════════════════════════════════════════════════════════

def _trade_response_to_order(resp) -> Order:
    return Order(
        order_id=resp.trade_id,
        exchange=resp.exchange,
        symbol=resp.symbol,
        side=_SIDE_FROM_PROTO.get(resp.side, OrderSide.BUY),
        quantity=getattr(resp, 'requested_quantity', resp.filled_quantity),
        filled_quantity=resp.filled_quantity,
        remaining_quantity=getattr(resp, 'remaining_quantity',
                                   max(0, getattr(resp, 'requested_quantity', resp.filled_quantity) - resp.filled_quantity)),
        order_type=OrderType.MARKET,
        price=resp.filled_price,
        avg_fill_price=resp.filled_price,
        commission=resp.commission,
        status=_STATUS_FROM_PROTO.get(resp.status, OrderStatus.FILLED),
        created_at=_ts_to_dt(resp.executed_at),
        updated_at=_ts_to_dt(resp.executed_at),
    )


def _proto_holding_to_position(h) -> Position:
    return Position(
        exchange=h.exchange,
        symbol=h.symbol,
        quantity=h.quantity,
        avg_cost=h.avg_cost,
        current_price=h.current_price,
        market_value=h.market_value,
        unrealized_pnl=h.unrealized_pnl,
        unrealized_pnl_pct=h.unrealized_pnl_pct,
    )
