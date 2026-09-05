"""Shared state for the news analysis LangGraph workflow."""

from typing import TypedDict


class AnalysisState(TypedDict):
    # Inputs
    news_id: str
    news_content: str
    news_source: str
    news_symbol: str
    news_exchange: str
    news_timestamp: str
    # Config (loaded at runtime)
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_flash_model: str
    # Prompt
    prompt: str
    # Agent loop state (persists across agent ↔ tool transitions)
    messages: list[dict]       # OpenAI-format conversation history
    round_count: int            # number of agent → tool cycles so far
    # LLM output
    llm_response_raw: str
    # Parsed
    sentiment: str
    confidence_score: float
    reasoning: str
    selected_symbol: str   # auto-selected stock in Case B
    # Context LLM config (for news searching)
    context_llm_url: str
    context_llm_key: str
    context_llm_model: str
    # News context (populated by fetch_news_context)
    positive_news_context: str
    negative_news_context: str
    # Trade
    trade_action: str
    # News filter
    _filtered: bool
    _filter_reason: str
    # Pre-analysis LLM call log (filter_news, identify_stock, fetch_news_context)
    _pre_analysis_log: list[dict]
