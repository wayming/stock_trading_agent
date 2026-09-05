"""Node: fetch_news_context — search for recent positive and negative news about the stock.

Uses a separately configurable LLM. Falls back to main LLM if not configured.
"""

import logging
from datetime import datetime, timedelta

from ..state import AnalysisState
from ..prompts import CONTEXT_PROMPT_POSITIVE, CONTEXT_PROMPT_NEGATIVE
from ..logging_utils import log_llm_call

logger = logging.getLogger(f"backend.{__name__}")


def fetch_news_context(state: AnalysisState) -> AnalysisState:
    """Call the context LLM to search for recent positive and negative news.

    Uses a separately configurable LLM.  Falls back to main LLM if not configured.
    """
    symbol = state.get("news_symbol", "").strip()
    if not symbol:
        logger.info("No stock symbol — skipping news context fetch")
        return state

    # Determine which LLM to use for context search
    ctx_url = state.get("context_llm_url", "") or state.get("llm_api_url", "")
    ctx_key = state.get("context_llm_key", "") or state.get("llm_api_key", "")
    ctx_model = state.get("context_llm_model", "") or state.get("llm_model", "gpt-4o")

    if not ctx_url:
        logger.info("No context LLM configured — skipping news context fetch")
        return state

    from llm import invoke_llm_simple
    six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    # Fetch positive news
    pos_prompt = CONTEXT_PROMPT_POSITIVE.format(symbol=symbol, six_months_ago=six_months_ago)
    try:
        pos_raw = invoke_llm_simple(
            api_url=ctx_url, api_key=ctx_key, model=ctx_model,
            system_prompt=pos_prompt,
            user_prompt=f"Search recent news for {symbol}",
            temperature=0.2, max_tokens=600, timeout=30.0,
        )
    except Exception as e:
        logger.warning(f"Context LLM positive news call failed: {e}")
        pos_raw = "[]"
    state["positive_news_context"] = pos_raw
    logger.info(f"Positive news context for {symbol}: {len(pos_raw)} chars")
    log_llm_call(state, "News Context (Positive)", ctx_model, pos_prompt, f"Search recent news for {symbol}", pos_raw)

    # Fetch negative news
    neg_prompt = CONTEXT_PROMPT_NEGATIVE.format(symbol=symbol, six_months_ago=six_months_ago)
    try:
        neg_raw = invoke_llm_simple(
            api_url=ctx_url, api_key=ctx_key, model=ctx_model,
            system_prompt=neg_prompt,
            user_prompt=f"Search recent news for {symbol}",
            temperature=0.2, max_tokens=600, timeout=30.0,
        )
    except Exception as e:
        logger.warning(f"Context LLM negative news call failed: {e}")
        neg_raw = "[]"
    state["negative_news_context"] = neg_raw
    logger.info(f"Negative news context for {symbol}: {len(neg_raw)} chars")
    log_llm_call(state, "News Context (Negative)", ctx_model, neg_prompt, f"Search recent news for {symbol}", neg_raw)

    # Append news context to the user message in the conversation
    _append_news_context_to_messages(state, symbol)

    return state


def _append_news_context_to_messages(state: AnalysisState, symbol: str):
    """Insert news context into the messages array before the agent loop."""
    pos_ctx = state.get("positive_news_context", "")
    neg_ctx = state.get("negative_news_context", "")

    if not pos_ctx.strip() and not neg_ctx.strip():
        return

    parts = [f"[Recent News Context for {symbol} — last 6 months]\n"]
    if pos_ctx.strip() and pos_ctx.strip() != "[]":
        parts.append(f"Positive events:\n{pos_ctx}\n")
    if neg_ctx.strip() and neg_ctx.strip() != "[]":
        parts.append(f"Negative events:\n{neg_ctx}\n")

    context_msg = "\n".join(parts)

    # Append as an additional user message (before any tool calls)
    messages = state["messages"]
    # Find the last user message and append to it, or insert after system
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            messages[i]["content"] = m["content"] + "\n\n" + context_msg
            break
    else:
        messages.insert(1, {"role": "user", "content": context_msg})

    logger.info(f"Appended news context ({len(context_msg)} chars) to user message")
