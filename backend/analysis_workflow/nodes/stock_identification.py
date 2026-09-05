"""Node: identify_stock — identify the best BUY candidate when only an exchange is given."""

import json
import re
import logging

from ..state import AnalysisState
from ..prompts import IDENTIFY_STOCK_SYSTEM_PROMPT
from ..logging_utils import log_llm_call

logger = logging.getLogger(f"backend.{__name__}")


def identify_stock(state: AnalysisState) -> AnalysisState:
    """Call LLM (no MCP tools) to identify the best BUY stock on the given exchange.

    Sets state["news_symbol"] and state["selected_symbol"] so the downstream
    build_prompt → agent_node path sees a concrete symbol to analyse.
    """
    exchange = state.get("news_exchange", "")
    content = state.get("news_content", "")
    url = state.get("llm_api_url", "")
    key = state.get("llm_api_key", "")
    model = state.get("llm_flash_model", "") or state.get("llm_model", "gpt-4o")

    logger.info(f"Identifying stock for exchange={exchange}")

    if not url:
        logger.warning("No LLM configured — cannot identify stock, falling through to neutral")
        return state

    user_msg = f"Exchange: {exchange}\n\nContent:\n{content}"

    try:
        from llm import invoke_llm_simple
        raw = invoke_llm_simple(
            api_url=url, api_key=key, model=model,
            system_prompt=IDENTIFY_STOCK_SYSTEM_PROMPT,
            user_prompt=user_msg,
            temperature=0.3, max_tokens=400, timeout=30.0,
        )
    except Exception as e:
        logger.error(f"Stock identification LLM call failed: {e}")
        return state

    logger.info(f"Stock identification response: {raw[:200]}")

    # Log this LLM call for the conversation view
    log_llm_call(state, "Identify Stock", model, IDENTIFY_STOCK_SYSTEM_PROMPT, user_msg, raw)

    # Parse JSON from response
    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            logger.warning("Failed to parse stock identification JSON")
            return state
    else:
        logger.warning("No JSON found in stock identification response")
        return state

    symbol = parsed.get("symbol", "").strip()
    company = parsed.get("company_name", "").strip()
    reasoning = parsed.get("reasoning", "")

    if symbol:
        state["news_symbol"] = symbol
        state["selected_symbol"] = f"{symbol} ({company})" if company else symbol
        state["_filtered"] = False
        logger.info(f"Identified stock: {symbol} ({company}) — {reasoning}")
    else:
        exchange = state.get("news_exchange", "")
        state["_filtered"] = True
        state["_filter_reason"] = f"No suitable BUY candidate found on exchange {exchange} for this news."
        logger.info(f"No suitable stock identified on exchange {exchange}")

    return state


def route_after_identify(state: AnalysisState):
    """After stock identification: continue if stock found, skip otherwise."""
    if state.get("_filtered"):
        return "skip_to_end"
    return "build_prompt"
