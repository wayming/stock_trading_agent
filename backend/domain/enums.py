"""Domain enums — pure, no framework dependency."""

from enum import Enum, auto


class OrderSide(Enum):
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()


class OrderStatus(Enum):
    NEW = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
