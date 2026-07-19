"""TradingStrategy — composes EntryRules, ExitRules, and a RiskRule."""

import logging

from .context import TradingContext
from .rules import EntryRule, ExitRule, RiskRule

logger = logging.getLogger(f"backend.{__name__}")


class TradingStrategy:
    """A composable trading strategy.

    Entry requires ALL rules to pass (AND logic).
    Exit triggers when ANY rule fires (OR logic).
    Position size is determined by a single RiskRule.

    Usage::

        strategy = TradingStrategy(
            entry_rules=[SentimentEntryRule(threshold=0.8)],
            exit_rules=[
                TakeProfitRule(profit_pct=0.05),
                StopLossRule(loss_pct=0.02),
                EndOfDayExitRule(),
            ],
            risk_rule=FixedPositionSize(amount=10000),
        )
    """

    def __init__(
        self,
        entry_rules: list[EntryRule] | None = None,
        exit_rules: list[ExitRule] | None = None,
        risk_rule: RiskRule | None = None,
    ):
        self.entry_rules: list[EntryRule] = entry_rules or []
        self.exit_rules: list[ExitRule] = exit_rules or []
        self.risk_rule: RiskRule | None = risk_rule

    # ── entry ─────────────────────────────────────────────

    def should_buy(self, ctx: TradingContext) -> bool:
        """All entry rules must pass."""
        if not self.entry_rules:
            return False
        return all(rule.should_enter(ctx) for rule in self.entry_rules)

    def should_short(self, ctx: TradingContext) -> bool:
        """All short-entry rules must pass.

        By default, shorts use the same entry_rules.  Override or supply
        dedicated short_entry_rules for asymmetric logic.
        """
        return self.should_buy(ctx)

    # ── exit ──────────────────────────────────────────────

    def should_sell(self, ctx: TradingContext) -> bool:
        """Any exit rule fires → close position."""
        if not ctx.holding:
            return False
        fired = [rule for rule in self.exit_rules if rule.should_exit(ctx)]
        if fired:
            logger.debug(
                "Exit triggered by: %s",
                [type(r).__name__ for r in fired],
            )
            return True
        return False

    # ── position size ─────────────────────────────────────

    def get_position_size(self, ctx: TradingContext) -> float:
        """How many dollars to allocate to this trade."""
        if self.risk_rule is None:
            return ctx.available_cash
        return self.risk_rule.allowed_position(ctx)

    # ── introspection ─────────────────────────────────────

    def describe(self) -> str:
        """Human-readable description of the strategy."""
        entry_names = [type(r).__name__ for r in self.entry_rules]
        exit_names = [type(r).__name__ for r in self.exit_rules]
        risk_name = type(self.risk_rule).__name__ if self.risk_rule else "None"
        return (
            f"TradingStrategy(\n"
            f"  entry  = {entry_names},\n"
            f"  exit   = {exit_names},\n"
            f"  risk   = {risk_name},\n"
            f")"
        )
