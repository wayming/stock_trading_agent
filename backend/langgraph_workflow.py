"""LangGraph workflow for news sentiment analysis with MCP tool-calling.

Pipeline graph:
  receive_news → build_prompt → agent_node ←→ execute_tools
                                    │ (no tool_calls)
                                    ↓
                              parse_response → evaluate_trade → END

The agent_node invokes the LLM with MCP tool definitions registered.
If the LLM returns tool_calls, should_continue routes to execute_tools,
which runs the tools via MCP and routes back to agent_node.  This repeats
until the LLM returns a plain text response (or MAX_TOOL_ROUNDS is hit).
"""

import json
import re
from typing import TypedDict, Literal

import httpx
from langgraph.graph import StateGraph, END

from models import SentimentLevel, TradeAction
from database import Database
import logging

#
# Constants
#

MAX_TOOL_ROUNDS = 5

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
    # Agent loop state (persists across agent ↔ tool transitions)
    messages: list[dict]       # OpenAI-format conversation history
    round_count: int            # number of agent → tool cycles so far
    # LLM output
    llm_response_raw: str
    # Parsed
    sentiment: str
    confidence_score: float
    reasoning: str
    # Trade
    trade_action: str


SYSTEM_PROMPT = """You are a professional stock market analyst. Analyze the sentiment of the given news for stock trading.

You have access to financial data tools. Use them to get real financial data for the stock mentioned in the news — this will help you make a more informed analysis:
- Use list_metrics first if you're unsure which metrics are available.
- Use get_data_period to check how much historical data is available.
- Use get_financials to fetch revenue, profit, EPS, PE, PB, margins, etc.

## Exchange detection rules

When calling tools, you MUST supply the correct exchange code. Determine it from the news symbol:

| Symbol pattern | Exchange | Examples |
|---|---|---|
| Pure digits, ≤5 chars | HKG | 0700, 6800, 0001 |
| Pure digits, 6 chars starting with 6 | SHA | 600519 |
| Pure digits, 6 chars starting with 0/3 | SHE | 302132 |
| Pure digits, 6 chars starting with 9 | SHA | 900948 |
| 3 uppercase letters | ASX | TCL, BHP, MGX |
| 1-5 uppercase letters (US) | NASDAQ | VSA, AAPL, TSLA |
| 1-5 uppercase letters (US) | NYSE | ZWS, GE, F |

If the news symbol contains an exchange prefix like "NASDAQ:WYNN" or "ASX:TCL", parse out the exchange and code separately.

IMPORTANT: Always try the exchange you think is most likely first. If the MCP tool returns "no data found", try another exchange before giving up.

Output MUST be a valid JSON object with these exact fields:
- "sentiment": one of ["超级利好", "普通利好", "neutral", "普通利空", "超级利空"]
- "confidence_score": a float between 0.0 and 1.0 indicating confidence
- "reasoning": a brief explanation (2-4 sentences) of why this sentiment was assigned in Chinese. Reference the financial data you retrieved if applicable.
- "translate": Chinese translation of the given news

Rules:
- 超级利好 (super bullish): News strongly suggests significant stock price increase (major earnings beat, breakthrough product, huge contract win, favorable macro policy changes)
- 普通利好 (bullish): News moderately positive (steady growth, minor contract wins, positive outlook)
- neutral: News has no clear directional impact or mixed signals
- 普通利空 (bearish): News moderately negative (minor earnings misses, regulatory headwinds)
- 超级利空 (super bearish): News strongly suggests significant price drop (major fraud, bankruptcy risk, catastrophic events)

Output ONLY the JSON object, no other text.
"""

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

    enabled = db.get_config("llm_enabled")
    llm_enabled = enabled != "false" if enabled is not None else True

    url = db.get_config("llm_api_url") or ""
    key = db.get_config("llm_api_key") or ""
    model = db.get_config("llm_model") or "gpt-4o"

    if not llm_enabled:
        logger.info("LLM is disabled — using keyword fallback")
        url = ""

    mcp_url = db.get_config("mcp_server_url") or ""
    logger.info(
        f"Loaded config: llm_url={url}, model={model}, "
        f"llm_enabled={llm_enabled}, mcp_url={mcp_url}"
    )
    state["llm_api_url"] = url
    state["llm_api_key"] = key
    state["llm_model"] = model
    return state


def build_prompt(state: AnalysisState) -> AnalysisState:
    """Construct the initial prompt and initialise the conversation messages."""
    user_msg = f"News Source: {state.get('news_source', 'unknown')}\n"
    user_msg += f"Stock Symbol: {state.get('news_symbol', 'N/A')}\n\n"
    user_msg += f"Content:\n{state.get('news_content', '')}"

    state["prompt"] = user_msg
    state["messages"] = [ 
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    state["round_count"] = 0
    logger.debug(f"Built prompt: {user_msg}")
    return state


#
# Agent node — one LLM call per transition
#

def agent_node(state: AnalysisState) -> AnalysisState:
    """Send the conversation (including any previous tool results) to the LLM.

    This node is re-entrant: every time execute_tools appends tool results
    to state["messages"], we come back here for another LLM call.
    """
    url = state.get("llm_api_url", "")
    key = state.get("llm_api_key", "")
    model = state.get("llm_model", "gpt-4o")

    # No LLM configured → keyword fallback (skip tool loop entirely)
    if not url:
        state["llm_response_raw"] = _keyword_fallback(state)
        return state

    tools = _get_tool_definitions()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    api_url = url.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/v1/chat/completions"

    payload: dict = {
        "model": model,
        "messages": state["messages"],
        "temperature": 0.3,
        "max_tokens": 800,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        resp = httpx.post(api_url, json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        state["llm_response_raw"] = json.dumps({
            "sentiment": "neutral",
            "confidence_score": 0.0,
            "reasoning": f"LLM API call failed: {e}",
        }, ensure_ascii=False)
        return state

    choice = data["choices"][0]
    msg = choice["message"]
    tool_calls = msg.get("tool_calls")

    if tool_calls:
        # LLM wants tools — append assistant message (with tool_calls), don't finalise yet
        state["messages"].append({
            "role": "assistant",
            "content": msg.get("content"),
            "tool_calls": tool_calls,
        })
        logger.info(
            f"Agent round {state['round_count']+1}: "
            f"LLM requested {len(tool_calls)} tool call(s)"
        )
    else:
        # Plain text response — analysis complete
        state["llm_response_raw"] = msg.get("content", "")
        logger.debug(f"LLM final response: {state['llm_response_raw'][:200]}")

    return state


#
# Execute tools node
#

def execute_tools(state: AnalysisState) -> AnalysisState:
    """Execute all pending tool calls and append results to messages."""
    messages = state["messages"]
    # The last message should be the assistant's tool_calls
    last_msg = messages[-1]
    tool_calls = last_msg.get("tool_calls", [])

    for tc in tool_calls:
        fn = tc["function"]
        name = fn["name"]
        try:
            args = json.loads(fn["arguments"])
        except json.JSONDecodeError:
            args = {}

        logger.info(f"  → {name}({json.dumps(args, ensure_ascii=False)})")
        result = _execute_mcp_tool(name, args)
        logger.debug(f"Tool result: {result}")
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": json.dumps(result, ensure_ascii=False, default=str),
        })

    state["round_count"] = state.get("round_count", 0) + 1
    return state


#
# Conditional edge — continue or exit the agent loop
#

def should_continue(state: AnalysisState) -> Literal["execute_tools", "parse_response"]:
    """Decide whether to execute tools or move on to parsing.

    Called after every agent_node invocation.
    """
    messages = state.get("messages", [])
    if not messages:
        return "parse_response"

    last_msg = messages[-1]
    has_tool_calls = bool(last_msg.get("tool_calls"))

    if has_tool_calls and state.get("round_count", 0) < MAX_TOOL_ROUNDS:
        return "execute_tools"

    return "parse_response"


#
# Tool execution helpers
#

def _get_tool_definitions() -> list[dict]:
    """Get MCP tool definitions for the LLM (static, no session needed)."""
    try:
        from mcp_client import get_tool_definitions
        return get_tool_definitions()
    except Exception as e:
        logger.warning(f"Could not get MCP tool definitions: {e}")
        return []


def _execute_mcp_tool(name: str, arguments: dict) -> dict | str:
    """Execute an MCP tool by name. Returns result dict or error string."""
    try:
        from mcp_client import get_mcp_client
        mcp = get_mcp_client()
        if mcp is None:
            return {"error": "MCP client not connected — is the MCP server running?"}
        result = mcp.call_tool(name, arguments)
        if result is None:
            return {"error": f"Tool {name} returned no data"}
        return result
    except Exception as e:
        logger.error(f"MCP tool {name} failed: {e}")
        return {"error": str(e)}


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
        reasoning = (
            f"Keyword-based analysis (LLM not configured). "
            f"Matched keywords: {', '.join(keywords_found[:10])}. "
            f"Sentiment: {sentiment}."
        )

    return json.dumps({
        "sentiment": sentiment,
        "confidence_score": round(confidence, 2),
        "reasoning": reasoning,
    }, ensure_ascii=False)


#
# Parse & evaluate
#

def parse_response(state: AnalysisState) -> AnalysisState:
    """Extract the JSON result from the LLM response."""
    raw = state.get("llm_response_raw", "{}")

    json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if json_match:
        raw = json_match.group(0)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

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
    """Construct and compile the LangGraph StateGraph.

    Edges:
        receive_news → build_prompt → agent_node
        agent_node → should_continue ──→ execute_tools → agent_node  (loop)
                                    └─→ parse_response  (exit)
        parse_response → evaluate_trade → END
    """
    graph = StateGraph(AnalysisState)

    graph.add_node("receive_news", receive_news)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("agent_node", agent_node)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("parse_response", parse_response)
    graph.add_node("evaluate_trade", evaluate_trade)

    graph.set_entry_point("receive_news")
    graph.add_edge("receive_news", "build_prompt")
    graph.add_edge("build_prompt", "agent_node")

    graph.add_conditional_edges(
        "agent_node",
        should_continue,
        {"execute_tools": "execute_tools", "parse_response": "parse_response"},
    )
    graph.add_edge("execute_tools", "agent_node")

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


def extract_conversation(state: AnalysisState) -> list[dict]:
    """Extract LLM conversation rounds from messages for frontend display.

    Returns a list of rounds, each containing the prompt sent to LLM
    and the response received (which may include tool_calls).

    Falls back to a single round from prompt/llm_response_raw if no
    message history is available (e.g. keyword fallback mode).
    """
    messages = state.get("messages", [])
    rounds: list[dict] = []
    pending_prompt: list[dict] = []

    if not messages:
        # No message history — build a single round from prompt + response
        prompt = state.get("prompt", "")
        response = state.get("llm_response_raw", "")
        if prompt or response:
            rounds.append({
                "round": 1,
                "prompt": prompt,
                "response": response,
                "type": "final",
            })
        return rounds

    for i, msg in enumerate(messages):
        role = msg.get("role", "")

        if role in ("system", "user"):
            pending_prompt.append(msg)

        elif role == "tool":
            # tool results are sent as the next prompt to the LLM
            pending_prompt.append(msg)

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # LLM requested tools — record this round
                rounds.append({
                    "round": len(rounds) + 1,
                    "prompt": _msg_to_text(pending_prompt),
                    "response": _format_tool_calls(tool_calls),
                    "type": "tool_call",
                })
                pending_prompt = []  # reset for next round
            else:
                # LLM gave final text response
                rounds.append({
                    "round": len(rounds) + 1,
                    "prompt": _msg_to_text(pending_prompt),
                    "response": msg.get("content", ""),
                    "type": "final",
                })
                pending_prompt = []

    if not rounds:
        # No rounds extracted — fall back to prompt / response pair
        prompt = state.get("prompt", "")
        response = state.get("llm_response_raw", "")
        if prompt or response:
            rounds.append({
                "round": 1,
                "prompt": prompt,
                "response": response,
                "type": "final",
            })

    return rounds


def _msg_to_text(msgs: list[dict]) -> str:
    """Convert a list of messages to a readable text block."""
    parts = []
    for m in msgs:
        role = m.get("role", "?")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"[System]\n{content}")
        elif role == "user":
            parts.append(f"[User]\n{content}")
        elif role == "tool":
            parts.append(f"[Tool Result — {m.get('tool_call_id', '?')[:12]}]\n{content}")
    return "\n\n".join(parts)


def _format_tool_calls(tool_calls: list[dict]) -> str:
    """Format tool calls as a human-readable string."""
    lines = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        lines.append(f"→ {fn.get('name', '?')}({fn.get('arguments', '{}')})")
    return "\n".join(lines)


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
        "messages": [],
        "round_count": 0,
        "llm_response_raw": "",
        "sentiment": "",
        "confidence_score": 0.0,
        "reasoning": "",
        "trade_action": "",
    }
    result = workflow.invoke(initial_state)
    return result
