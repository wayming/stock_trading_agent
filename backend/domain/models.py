"""Domain models — pure @dataclass, no ORM, no Pydantic, no framework.

These are the canonical trading objects.  Every broker adapter maps its
native representation (proto, REST, API response) into these.
"""

from dataclasses import dataclass, field
from datetime import datetime
from .enums import OrderSide, OrderType, OrderStatus


# ═══════════════════════════════════════════════════════════════
# OrderRequest — submitted by strategy
# ═══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class OrderRequest:
    exchange: str
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    price: float | None = None
    client_order_id: str | None = None


# ═══════════════════════════════════════════════════════════════
# Order — the life-cycle of a submitted order
# ═══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Order:
    order_id: str
    exchange: str
    symbol: str
    side: OrderSide
    quantity: int
    filled_quantity: int = 0
    remaining_quantity: int = 0
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    avg_fill_price: float | None = None
    commission: float = 0.0
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════════
# Trade — a single fill (one order can produce many trades)
# ═══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Trade:
    trade_id: str
    order_id: str
    exchange: str
    symbol: str
    side: OrderSide
    quantity: int
    price: float
    commission: float = 0.0
    executed_at: datetime = field(default_factory=datetime.now)


# ═══════════════════════════════════════════════════════════════
# Position — current holding in a symbol
# ═══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Position:
    exchange: str
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


# ═══════════════════════════════════════════════════════════════
# Account — portfolio summary
# ═══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Account:
    cash: float
    market_value: float = 0.0
    total_asset: float = 0.0
    unrealized_pnl: float = 0.0
    initial_fund: float = 0.0


# ═══════════════════════════════════════════════════════════════
# Quote — market data snapshot
# ═══════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Quote:
    exchange: str
    symbol: str
    last_price: float
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    previous_close: float = 0.0
    volume: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
