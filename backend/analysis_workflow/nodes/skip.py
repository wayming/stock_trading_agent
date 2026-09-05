"""Node: skip_to_end — return neutral immediately (no LLM calls)."""

import json
import logging

from ..state import AnalysisState

logger = logging.getLogger(f"backend.{__name__}")


def skip_to_end(state: AnalysisState) -> AnalysisState:
    """Return neutral immediately — no LLM calls.

    Uses _filter_reason to produce a context-appropriate message.
    """
    reason = state.get("_filter_reason", "")
    exchange = state.get("news_exchange", "")

    if reason:
        # Classification or identification already provided the reason
        display_reason = reason
    elif not exchange:
        display_reason = "No stock symbol or exchange provided — insufficient information."
    else:
        display_reason = f"No actionable BUY opportunity identified on exchange {exchange}."

    logger.info(f"Skipping to end: {display_reason}")
    state["llm_response_raw"] = json.dumps({
        "sentiment": "neutral",
        "confidence_score": 0.3,
        "reasoning": display_reason,
        "selected_symbol": "",
    }, ensure_ascii=False)
    state["sentiment"] = "neutral"
    state["confidence_score"] = 0.3
    state["reasoning"] = display_reason
    state["selected_symbol"] = ""
    state["trade_action"] = "NONE"
    return state
