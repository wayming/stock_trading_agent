"""LangGraph workflow for news sentiment analysis.

Pipeline stages (5 nodes, linear):
  1. receive_news   — load LLM config from DB
  2. build_prompt   — construct system + user prompt
  3. call_llm       — send to OpenAI-compatible API
  4. parse_response — extract JSON, validate sentiment
  5. evaluate_trade — map sentiment to trade action
"""

import json
import re
from typing import TypedDict, Optional

import httpx
from langgraph.graph import StateGraph, END

from models import SentimentLevel, TradeAction
from database import Database
import logging

#
# State
#

class AnalysisState(TypedDict):
    # Inputs
    news_id: str
    news_content: str
    news_source: str
    news_symbol: str
    news_timestamp: str
    # Config (loaded at runtime)
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    # Prompt
    prompt: str
    # LLM output
    llm_response_raw: str
    # Parsed
    sentiment: str
    confidence_score: float
    reasoning: str
    # Trade
    trade_action: str


SYSTEM_PROMPT = """You are a professional stock market analyst. Analyze the sentiment of the given news for stock trading.

Output MUST be a valid JSON object with these exact fields:
- "sentiment": one of ["超级利好", "普通利好", "neutral", "普通利空", "超级利空"]
- "confidence_score": a float between 0.0 and 1.0 indicating confidence
- "reasoning": a brief explanation (2-4 sentences) of why this sentiment was assigned

Rules:
- 超级利好 (super bullish): News strongly suggests significant stock price increase (major earnings beat, breakthrough product, huge contract win, favorable macro policy changes)
- 普通利好 (bullish): News moderately positive (steady growth, minor contract wins, positive outlook)
- neutral: News has no clear directional impact or mixed signals
- 普通利空 (bearish): News moderately negative (minor earnings misses, regulatory headwinds)
- 超级利空 (super bearish): News strongly suggests significant price drop (major fraud, bankruptcy risk, catastrophic events)

Output ONLY the JSON object, no other text."""

db: Database = None
logger = logging.getLogger(f"backend.{__name__}")
#
# Node functions
#

def receive_news(state: AnalysisState) -> AnalysisState:
    """Load LLM config from the database and pass through news fields."""
    if db is None:
        logger.error("Database not initialized")
        raise ValueError("Database not initialized")
    url = db.get_config("llm_api_url") or ""
    key = db.get_config("llm_api_key") or ""
    model = db.get_config("llm_model") or "gpt-4o"
    logger.info(f"Loaded LLM config: url={url}, model={model}")
    state["llm_api_url"] = url
    state["llm_api_key"] = key
    state["llm_model"] = model
    return state


def build_prompt(state: AnalysisState) -> AnalysisState:
    """Construct the complete prompt for the LLM."""
    user_msg = f"News Source: {state.get('news_source', 'unknown')}\n"
    user_msg += f"Stock Symbol: {state.get('news_symbol', 'N/A')}\n\n"
    user_msg += f"Content:\n{state.get('news_content', '')}"

    state["prompt"] = user_msg
    return state


#
# Keyword-based fallback (when no real LLM API configured)
#

SUPER_BULLISH_KEYWORDS = [
    "暴涨", "涨停", "翻倍", "重大利好", "远超预期", "超级利好",
    "历史新高", "获得重大合同", "突破性进展", "重磅",
    "soar", "skyrocket", "breakthrough", "record high",
]

BULLISH_KEYWORDS = [
    "上涨", "增长", "利好", "盈利", "扩大", "上升", "向好",
    "超出预期", "回购", "增持", "分红", "扩产",
    "growth", "profit", "beat", "exceed", "upgrade",
]

BEARISH_KEYWORDS = [
    "下跌", "下滑", "下降", "利空", "亏损", "减少", "萎缩",
    "低于预期", "减持", "裁员", "抛售",
    "decline", "loss", "miss", "downgrade", "drop",
]

SUPER_BEARISH_KEYWORDS = [
    "暴跌", "跌停", "崩盘", "破产", "退市", "暴雷", "造假",
    "重大利空", "腰斩", "严重亏损", "危机", "调查", "处罚",
    "crash", "bankruptcy", "fraud", "scandal", "collapse",
]


def _keyword_fallback(state: AnalysisState) -> str:
    """Simple keyword-based sentiment classification when no LLM is configured."""
    content = state.get("news_content", "")
    content_lower = content.lower()

    super_bullish = sum(1 for kw in SUPER_BULLISH_KEYWORDS if kw in content or kw.lower() in content_lower)
    bullish = sum(1 for kw in BULLISH_KEYWORDS if kw in content or kw.lower() in content_lower)
    bearish = sum(1 for kw in BEARISH_KEYWORDS if kw in content or kw.lower() in content_lower)
    super_bearish = sum(1 for kw in SUPER_BEARISH_KEYWORDS if kw in content or kw.lower() in content_lower)

    scores = {
        SentimentLevel.SUPER_BULLISH.value: super_bullish * 3,
        SentimentLevel.BULLISH.value: bullish,
        SentimentLevel.BEARISH.value: bearish,
        SentimentLevel.SUPER_BEARISH.value: super_bearish * 3,
    }
    max_sentiment = max(scores, key=scores.get)
    max_score = scores[max_sentiment]

    if max_score == 0:
        sentiment = SentimentLevel.NEUTRAL.value
        confidence = 0.4
        reasoning = "No clear sentiment keywords detected in the news content."
    else:
        sentiment = max_sentiment
        confidence = min(0.9, 0.5 + max_score * 0.1)
        keywords_found = [kw for kw in (
            SUPER_BULLISH_KEYWORDS + BULLISH_KEYWORDS +
            BEARISH_KEYWORDS + SUPER_BEARISH_KEYWORDS
        ) if kw in content or kw.lower() in content_lower]
        reasoning = f"Keyword-based analysis (LLM not configured). Matched keywords: {', '.join(keywords_found[:10])}. Sentiment: {sentiment}."

    return json.dumps({
        "sentiment": sentiment,
        "confidence_score": round(confidence, 2),
        "reasoning": reasoning,
    }, ensure_ascii=False)


def call_llm(state: AnalysisState) -> AnalysisState:
    """Send the prompt to the configured LLM API endpoint."""
    url = state.get("llm_api_url", "")
    key = state.get("llm_api_key", "")
    model = state.get("llm_model", "gpt-4o")

    if not url:
        state["llm_response_raw"] = _keyword_fallback(state)
        return state

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": state["prompt"]},
        ],
        "temperature": 0.3,
        "max_tokens": 500,
    }

    try:
        # Ensure URL ends with /chat/completions if it doesn't already
        api_url = url.rstrip("/")
        if not api_url.endswith("/chat/completions"):
            api_url += "/v1/chat/completions"

        resp = httpx.post(api_url, json=payload, headers=headers, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        state["llm_response_raw"] = data["choices"][0]["message"]["content"]
    except Exception as e:
        state["llm_response_raw"] = json.dumps({
            "sentiment": "neutral",
            "confidence_score": 0.0,
            "reasoning": f"LLM API call failed: {str(e)}"
        })
    return state


def parse_response(state: AnalysisState) -> AnalysisState:
    """Extract the JSON result from the LLM response."""
    raw = state.get("llm_response_raw", "{}")

    # Try to extract a JSON object from the response
    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if json_match:
        raw = json_match.group(0)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

    sentiment = parsed.get("sentiment", "neutral")
    # Validate sentiment
    valid = [e.value for e in SentimentLevel]
    if sentiment not in valid:
        # Fallback: search for keywords in the raw text
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


#
# Build graph
#

def build_workflow() -> StateGraph:
    """Construct and compile the LangGraph StateGraph."""
    graph = StateGraph(AnalysisState)

    graph.add_node("receive_news", receive_news)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("call_llm", call_llm)
    graph.add_node("parse_response", parse_response)
    graph.add_node("evaluate_trade", evaluate_trade)

    graph.set_entry_point("receive_news")
    graph.add_edge("receive_news", "build_prompt")
    graph.add_edge("build_prompt", "call_llm")
    graph.add_edge("call_llm", "parse_response")
    graph.add_edge("parse_response", "evaluate_trade")
    graph.add_edge("evaluate_trade", END)

    return graph.compile()


# Singleton
_workflow = None


def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_workflow()
    return _workflow


def run_analysis(news_item: dict) -> AnalysisState:
    """Run the full analysis pipeline on a news item. Returns the final state."""
    workflow = get_workflow()
    initial_state: AnalysisState = {
        "news_id": news_item.get("id", ""),
        "news_content": news_item.get("content", ""),
        "news_source": news_item.get("source", ""),
        "news_symbol": news_item.get("symbol", ""),
        "news_timestamp": news_item.get("timestamp", ""),
        "llm_api_url": "",
        "llm_api_key": "",
        "llm_model": "gpt-4o",
        "prompt": "",
        "llm_response_raw": "",
        "sentiment": "",
        "confidence_score": 0.0,
        "reasoning": "",
        "trade_action": "",
    }
    result = workflow.invoke(initial_state)
    return result
