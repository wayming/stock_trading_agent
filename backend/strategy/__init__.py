"""Composable trading strategy framework.

Inspired by QuantConnect / Backtrader / Zipline.

Build strategies by composing EntryRules, ExitRules, and a RiskRule::

    from strategy import TradingStrategy
    from strategy.rules import (
        SentimentEntryRule,
        TakeProfitRule,
        StopLossRule,
        EndOfDayExitRule,
        FixedPositionSize,
    )

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

from .context import TradingContext
from .strategy import TradingStrategy
from .rules import (
    # ABCs
    EntryRule,
    ExitRule,
    RiskRule,
    # Entry
    SentimentEntryRule,
    SuperBullishOnlyRule,
    # Exit
    TakeProfitRule,
    StopLossRule,
    EndOfDayExitRule,
    MaxHoldingDaysRule,
    SentimentReversalRule,
    TrailingStopRule,
    # Risk
    FixedPositionSize,
    PercentageOfCash,
    KellyPositionSize,
)

__all__ = [
    "TradingContext",
    "TradingStrategy",
    # ABCs
    "EntryRule",
    "ExitRule",
    "RiskRule",
    # Entry
    "SentimentEntryRule",
    "SuperBullishOnlyRule",
    # Exit
    "TakeProfitRule",
    "StopLossRule",
    "EndOfDayExitRule",
    "MaxHoldingDaysRule",
    "SentimentReversalRule",
    "TrailingStopRule",
    # Risk
    "FixedPositionSize",
    "PercentageOfCash",
    "KellyPositionSize",
]
