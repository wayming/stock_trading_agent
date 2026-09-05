"""Node: receive_news — load LLM config from DB and pass through news fields."""

import logging

from ..state import AnalysisState

logger = logging.getLogger(f"backend.{__name__}")


def receive_news(state: AnalysisState) -> AnalysisState:
    """Load LLM config from the database and pass through news fields."""
    # Lazy import to avoid circular dependency at module level
    from ..runner import _get_db
    db = _get_db()

    if db is None:
        logger.error("Database not initialized")
        raise ValueError("Database not initialized")

    enabled = db.get_config("llm_enabled")
    llm_enabled = enabled != "false" if enabled is not None else True

    url = db.get_config("llm_api_url") or ""
    key = db.get_config("llm_api_key") or ""
    model = db.get_config("llm_model") or "gpt-4o"
    flash_model = db.get_config("llm_flash_model") or ""

    mcp_url = db.get_config("mcp_server_url") or ""
    ctx_url = db.get_config("context_llm_url") or ""
    ctx_key = db.get_config("context_llm_key") or ""
    ctx_model = db.get_config("context_llm_model") or ""

    if not llm_enabled:
        logger.info("LLM is disabled — using keyword fallback for ALL LLM calls")
        url = ""
        key = ""
        flash_model = ""
        ctx_url = ""
        ctx_key = ""
    logger.info(
        f"Loaded config: llm_url={url}, model={model}, "
        f"flash_model={flash_model}, llm_enabled={llm_enabled}, mcp_url={mcp_url}, "
        f"ctx_llm={'configured' if ctx_url else 'not set'}"
    )
    state["llm_api_url"] = url
    state["llm_api_key"] = key
    state["llm_model"] = model
    state["llm_flash_model"] = flash_model
    state["context_llm_url"] = ctx_url
    state["context_llm_key"] = ctx_key
    state["context_llm_model"] = ctx_model
    state["positive_news_context"] = ""
    state["negative_news_context"] = ""
    state["_filtered"] = False
    state["_filter_reason"] = ""
    state["_pre_analysis_log"] = []
    return state
