"""Node: build_prompt — construct the initial prompt and conversation messages."""

import logging

from ..state import AnalysisState
from ..prompts import MAIN_ANALYSIS_SYSTEM_PROMPT

logger = logging.getLogger(f"backend.{__name__}")


def build_prompt(state: AnalysisState) -> AnalysisState:
    """Construct the initial prompt and initialise the conversation messages."""
    exchange = state.get("news_exchange", "")
    symbol = state.get("news_symbol", "")

    user_msg = f"Exchange: {exchange or 'N/A'}\n"
    user_msg += f"Stock Symbol: {symbol or 'N/A'}\n"
    user_msg += f"News Source: {state.get('news_source', 'unknown')}\n\n"
    user_msg += f"Content:\n{state.get('news_content', '')}"

    state["prompt"] = user_msg
    state["messages"] = [
        {"role": "system", "content": MAIN_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    state["round_count"] = 0
    logger.debug(
        "Built prompt:\n=== SYSTEM ===\n%s\n=== USER ===\n%s\n=== END PROMPT ===",
        MAIN_ANALYSIS_SYSTEM_PROMPT, user_msg,
    )
    return state
