"""Public entry point for running the news analysis workflow.

Also holds the db singleton and workflow singleton used across the package.
"""

import logging

from .state import AnalysisState
from .graph import build_workflow

logger = logging.getLogger(f"backend.{__name__}")

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

#: Database instance injected by services.py on startup.
#  TODO: replace with dependency injection so nodes don't depend on module global.
db = None

#: Compiled LangGraph workflow (lazy-init).
_workflow = None


def _get_db():
    """Return the module-level db singleton. Used for lazy imports in submodules."""
    global db
    return db


def get_workflow():
    """Return the compiled LangGraph workflow singleton."""
    global _workflow
    if _workflow is None:
        _workflow = build_workflow()
    return _workflow


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_analysis(news_item: dict) -> AnalysisState:
    """Run the full analysis pipeline on a news item. Returns the final state."""
    workflow = get_workflow()
    initial_state: AnalysisState = {
        "news_id": news_item.get("id", ""),
        "news_content": news_item.get("content", ""),
        "news_source": news_item.get("source", ""),
        "news_symbol": news_item.get("symbol", ""),
        "news_exchange": news_item.get("exchange", ""),
        "news_timestamp": news_item.get("timestamp", ""),
        "llm_api_url": "",
        "llm_api_key": "",
        "llm_model": "gpt-4o",
        "llm_flash_model": "",
        "prompt": "",
        "messages": [],
        "round_count": 0,
        "llm_response_raw": "",
        "sentiment": "",
        "confidence_score": 0.0,
        "reasoning": "",
        "selected_symbol": "",
        "context_llm_url": "",
        "context_llm_key": "",
        "context_llm_model": "",
        "positive_news_context": "",
        "negative_news_context": "",
        "trade_action": "",
        "_filtered": False,
        "_filter_reason": "",
        "_pre_analysis_log": [],
    }
    result = workflow.invoke(initial_state)
    return result
