"""Node: classify_news — categorize news before entering the main analysis pipeline.

Categories:
  - Noise  → skip (price movement / market recap)
  - Macro  → skip (no clear first-order earnings benefit)
  - Company → continue (company-specific impact)
  - Industry → continue (sector-wide impact, stock identification needed)

Falls back gracefully: if the LLM is unavailable, the news passes through.
"""

import json
import re
import logging

from ..state import AnalysisState
from ..prompts import NEWS_CLASSIFY_SYSTEM_PROMPT
from ..logging_utils import log_llm_call

logger = logging.getLogger(f"backend.{__name__}")


def classify_news(state: AnalysisState) -> AnalysisState:
    """Use flash model to classify news before entering the main analysis pipeline."""
    content = state.get("news_content", "")
    if not content or not content.strip():
        state["_filtered"] = False
        state["_filter_reason"] = ""
        return state

    url = state.get("llm_api_url", "")
    key = state.get("llm_api_key", "")
    model = state.get("llm_flash_model", "") or state.get("llm_model", "gpt-4o")

    if not url:
        logger.info("No LLM configured — skipping news classification")
        state["_filtered"] = False
        state["_filter_reason"] = ""
        return state

    user_prompt = f"Classify this news:\n\n{content}"
    try:
        from llm import invoke_llm_simple
        raw = invoke_llm_simple(
            api_url=url, api_key=key, model=model,
            system_prompt=NEWS_CLASSIFY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0, max_tokens=150, timeout=15.0,
        )
    except Exception as e:
        logger.error(f"News classification LLM call failed: {e}")
        state["_filtered"] = False
        state["_filter_reason"] = ""
        return state

    logger.debug(f"News classification response: {raw[:200]}")

    # Log this LLM call for the conversation view
    log_llm_call(state, "News Classification", model, NEWS_CLASSIFY_SYSTEM_PROMPT, user_prompt, raw)

    # Parse JSON from response
    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            category = parsed.get("category", "").strip()
            reason = parsed.get("reason", "")

            if category in ("Noise", "Macro"):
                state["_filtered"] = True
                state["_filter_reason"] = f"[{category}] {reason}"
                logger.info(f"News skipped ({category}): {reason} — {content[:80]}...")
                return state
            elif category in ("Company", "Industry"):
                state["_filtered"] = False
                state["_filter_reason"] = f"[{category}] {reason}"
                logger.info(f"News accepted ({category}): {reason}")
                return state
        except json.JSONDecodeError:
            logger.warning("Failed to parse news classification JSON response")

    # Fallback: if parsing fails, let the news through
    state["_filtered"] = False
    state["_filter_reason"] = ""
    return state


def route_after_classify(state: AnalysisState):
    """Route after classification: skip Noise/Macro, continue Company/Industry."""
    if state.get("_filtered"):
        return "skip_to_end"
    if state.get("news_symbol", "").strip():
        return "build_prompt"
    if state.get("news_exchange", "").strip():
        return "identify_stock"
    return "skip_to_end"
