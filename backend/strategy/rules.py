"""Abstract base classes and concrete rule implementations.

Rules are stateless callables that receive a TradingContext and return a decision.
"""

from abc import ABC, abstractmethod

from .context import TradingContext


# ═══════════════════════════════════════════════════════════════
# Abstract base classes
# ═══════════════════════════════════════════════════════════════

class EntryRule(ABC):
    """Return True when conditions are right to enter a position."""

    @abstractmethod
    def should_enter(self, ctx: TradingContext) -> bool:
        ...


class ExitRule(ABC):
    """Return True when current position should be closed."""

    @abstractmethod
    def should_exit(self, ctx: TradingContext) -> bool:
        ...


class RiskRule(ABC):
    """Return the maximum position size ($) for this trade."""

    @abstractmethod
    def allowed_position(self, ctx: TradingContext) -> float:
        ...


# ═══════════════════════════════════════════════════════════════
# Entry rules
# ═══════════════════════════════════════════════════════════════

class SentimentEntryRule(EntryRule):
    """Enter when LLM sentiment confidence exceeds a threshold."""

    def __init__(self, threshold: float = 0.8):
        self.threshold = threshold

    def should_enter(self, ctx: TradingContext) -> bool:
        return ctx.sentiment_score >= self.threshold


class SuperBullishOnlyRule(EntryRule):
    """Only enter on 超级利好 — ignores confidence."""

    def should_enter(self, ctx: TradingContext) -> bool:
        return ctx.sentiment_label == "超级利好"


# ═══════════════════════════════════════════════════════════════
# Exit rules
# ═══════════════════════════════════════════════════════════════

class TakeProfitRule(ExitRule):
    """Exit when price reaches entry * (1 + profit_pct)."""

    def __init__(self, profit_pct: float = 0.05):
        self.profit_pct = profit_pct

    def should_exit(self, ctx: TradingContext) -> bool:
        if ctx.entry_price is None:
            return False
        return ctx.price >= ctx.entry_price * (1 + self.profit_pct)


class StopLossRule(ExitRule):
    """Exit when price falls to entry * (1 - loss_pct)."""

    def __init__(self, loss_pct: float = 0.02):
        self.loss_pct = loss_pct

    def should_exit(self, ctx: TradingContext) -> bool:
        if ctx.entry_price is None:
            return False
        return ctx.price <= ctx.entry_price * (1 - self.loss_pct)


class EndOfDayExitRule(ExitRule):
    """Exit after holding for 1 day."""

    def should_exit(self, ctx: TradingContext) -> bool:
        return ctx.holding and ctx.holding_days >= 1


class MaxHoldingDaysRule(ExitRule):
    """Exit when a position has been held longer than N days."""

    def __init__(self, days: int = 3):
        self.days = days

    def should_exit(self, ctx: TradingContext) -> bool:
        return ctx.holding and ctx.holding_days >= self.days


class SentimentReversalRule(ExitRule):
    """Exit when sentiment turns bearish while holding."""

    def should_exit(self, ctx: TradingContext) -> bool:
        if not ctx.holding:
            return False
        return ctx.sentiment_label in ("普通利空", "超级利空")


class TrailingStopRule(ExitRule):
    """Exit when price retraces by `trail_pct` from the highest seen price.

    `extra["high_water_mark"]` must be maintained externally (e.g. by the engine).
    """

    def __init__(self, trail_pct: float = 0.03):
        self.trail_pct = trail_pct

    def should_exit(self, ctx: TradingContext) -> bool:
        if not ctx.holding:
            return False
        high = ctx.extra.get("high_water_mark", ctx.price)
        return ctx.price <= high * (1 - self.trail_pct)


# ═══════════════════════════════════════════════════════════════
# Risk / position sizing
# ═══════════════════════════════════════════════════════════════

class FixedPositionSize(RiskRule):
    """Always return the same dollar amount."""

    def __init__(self, amount: float = 10000.0):
        self.amount = amount

    def allowed_position(self, ctx: TradingContext) -> float:
        return min(self.amount, ctx.available_cash)


class PercentageOfCash(RiskRule):
    """Risk a fixed percentage of available cash."""

    def __init__(self, pct: float = 0.25):
        self.pct = pct

    def allowed_position(self, ctx: TradingContext) -> float:
        return ctx.available_cash * self.pct


class KellyPositionSize(RiskRule):
    """Kelly criterion: f* = win_prob - (1 - win_prob) / win_loss_ratio."""

    def __init__(self, win_prob: float = 0.55, win_loss_ratio: float = 2.0):
        self.win_prob = win_prob
        self.win_loss_ratio = win_loss_ratio

    def allowed_position(self, ctx: TradingContext) -> float:
        kelly = self.win_prob - (1 - self.win_prob) / self.win_loss_ratio
        kelly = max(0.0, min(kelly, 0.25))  # cap at 25% to avoid overbetting
        return ctx.available_cash * kelly
