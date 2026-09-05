"""Nodes: parse_response and evaluate_trade — extract JSON, map sentiment to trade action."""

import json
import re
import logging

from models import SentimentLevel, TradeAction
from ..state import AnalysisState

logger = logging.getLogger(f"backend.{__name__}")


def _extract_json_object(raw: str) -> dict:
    """Extract the first JSON object from a raw string. Returns empty dict on failure."""
    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def parse_response(state: AnalysisState) -> AnalysisState:
    """Extract the JSON result from the LLM response."""
    raw = state.get("llm_response_raw", "{}")
    parsed = _extract_json_object(raw)

    sentiment = parsed.get("sentiment", "neutral")
    valid = [e.value for e in SentimentLevel]
    if sentiment not in valid:
        raw_lower = state.get("llm_response_raw", "").lower()
        if "超级利好" in raw or "super bullish" in raw_lower:
            sentiment = SentimentLevel.SUPER_BULLISH.value
        elif "超级利空" in raw or "super bearish" in raw_lower:
            sentiment = SentimentLevel.SUPER_BEARISH.value
        elif "利好" in raw or "bullish" in raw_lower:
            sentiment = SentimentLevel.BULLISH.value
        elif "利空" in raw or "bearish" in raw_lower:
            sentiment = SentimentLevel.BEARISH.value
        else:
            sentiment = SentimentLevel.NEUTRAL.value

    state["sentiment"] = sentiment
    state["confidence_score"] = float(parsed.get("confidence_score", 0.5))
    state["reasoning"] = str(parsed.get("reasoning", ""))
    state["selected_symbol"] = str(parsed.get("selected_symbol", ""))
    return state


def evaluate_trade(state: AnalysisState) -> AnalysisState:
    """Map sentiment to trade action."""
    sentiment = state.get("sentiment", "")
    if sentiment == SentimentLevel.SUPER_BULLISH.value:
        state["trade_action"] = TradeAction.BUY.value
    elif sentiment == SentimentLevel.SUPER_BEARISH.value:
        state["trade_action"] = TradeAction.SHORT.value
    else:
        state["trade_action"] = TradeAction.NONE.value
    return state
