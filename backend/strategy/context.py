"""TradingContext — immutable-ish snapshot passed to all rules."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TradingContext:
    """A snapshot of the current trading environment.

    Passed to every EntryRule, ExitRule, and RiskRule.
    """

    now: datetime

    symbol: str = ""

    # --- Sentiment (from LLM analysis) ---
    sentiment_score: float = 0.0       # 0.0–1.0 confidence from LLM
    sentiment_label: str = "neutral"   # 超级利好 / 普通利好 / neutral / 普通利空 / 超级利空

    # --- Price ---
    price: float = 0.0                 # current market price
    entry_price: float | None = None   # entry price if holding a position

    # --- Position ---
    holding: bool = False              # currently holding this symbol?
    holding_days: int = 0              # how many days held
    position_size: float = 0.0         # current position value ($)

    # --- Account ---
    available_cash: float = 0.0        # buying power

    # --- Extra context (extensible) ---
    extra: dict = field(default_factory=dict)
