"""Default trading strategy configuration.

Import ``default_strategy`` to get a ready-to-use strategy instance.
"""

from strategy import TradingStrategy
from strategy.rules import (
    SentimentEntryRule,
    TakeProfitRule,
    StopLossRule,
    EndOfDayExitRule,
    FixedPositionSize,
)


default_strategy = TradingStrategy(
    entry_rules=[
        SentimentEntryRule(threshold=0.8),
    ],
    exit_rules=[
        TakeProfitRule(profit_pct=0.05),
        StopLossRule(loss_pct=0.02),
        EndOfDayExitRule(),
    ],
    risk_rule=FixedPositionSize(amount=10000.0),
)
