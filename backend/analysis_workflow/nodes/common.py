from quantsandbox.stock_trading_agent.backend.analysis_workflow.prompts import CLASSIFY_NEWS_SYSTEM_PROMPT
from quantsandbox.stock_trading_agent.backend.analysis_workflow.logging_utils import log_llm_call
from pydantic import BaseModel
from enum import Enum
import re
import json
import logging
logger = logging.getLogger(f"backend.{__name__}")

class NewsCategory(Enum):
    NOISE = "Noise"
    MACRO = "Macro"
    COMPANY = "Company"
    INDUSTRY = "Industry"

def call_llm_if_specified(system_prompt: str, user_prompt: str, state: dict, node_name: str, output_schema: BaseModel):
    url = state.get("llm_api_url", "")
    key = state.get("llm_api_key", "")
    model = state.get("llm_flash_model", "") or state.get("llm_model", "gpt-4o")
    
    if not url:
        logger.info("No LLM configured — skipping")
        return None
    raw: str = ""
    try:
        from llm import invoke_llm_simple
        raw = invoke_llm_simple(
            api_url=url, api_key=key, model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0, max_tokens=150, timeout=15.0,
        )
        # Log this LLM call for the conversation view
        log_llm_call(state, node_name, model, system_prompt, user_prompt, raw)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None
    
    # Parse JSON from response
    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            parsed_obj = output_schema.model_validate_json(raw)
            logger.info(f"Parsed JSON: {parsed_obj}")
            return parsed_obj

        except json.JSONDecodeError:
            logger.warning("Failed to parse news classification JSON response")
    pass
