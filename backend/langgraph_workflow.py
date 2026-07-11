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
    # Context LLM config (for news searching)
    context_llm_url: str
    context_llm_key: str
    context_llm_model: str
    # News context (populated by fetch_news_context)
    positive_news_context: str
    negative_news_context: str
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
    ctx_url = db.get_config("context_llm_url") or ""
    ctx_key = db.get_config("context_llm_key") or ""
    ctx_model = db.get_config("context_llm_model") or ""
    logger.info(
        f"Loaded config: llm_url={url}, model={model}, "
        f"llm_enabled={llm_enabled}, mcp_url={mcp_url}, "
        f"ctx_llm={'configured' if ctx_url else 'not set'}"
    )
    state["llm_api_url"] = url
    state["llm_api_key"] = key
    state["llm_model"] = model
    state["context_llm_url"] = ctx_url
    state["context_llm_key"] = ctx_key
    state["context_llm_model"] = ctx_model
    state["positive_news_context"] = ""
    state["negative_news_context"] = ""
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
# Fetch news context node — calls context LLM for positive/negative news
#

CONTEXT_PROMPT_POSITIVE = """You are a financial news researcher. List up to 5 significant POSITIVE events or news items about the stock {symbol} from the last 6 months (since {six_months_ago}).

Rules:
- Only include real, verifiable events (earnings beats, product launches, analyst upgrades, contract wins, etc.)
- If you are uncertain or don't know, return fewer items or say "no specific positive events found"
- Return ONLY a JSON array of objects with fields: "date" (YYYY-MM-DD), "event" (one sentence), "impact" (one sentence)

Example format:
[
  {{"date": "2026-03-15", "event": "Q4 earnings beat estimates by 12%", "impact": "Stock rose 5% on earnings day"}}
]

If no positive events are known, return: []"""

CONTEXT_PROMPT_NEGATIVE = """You are a financial news researcher. List up to 5 significant NEGATIVE events or news items about the stock {symbol} from the last 6 months (since {six_months_ago}).

Rules:
- Only include real, verifiable events (earnings misses, regulatory issues, product recalls, analyst downgrades, etc.)
- If you are uncertain or don't know, return fewer items or say "no specific negative events found"
- Return ONLY a JSON array of objects with fields: "date" (YYYY-MM-DD), "event" (one sentence), "impact" (one sentence)

Example format:
[
  {{"date": "2026-02-10", "event": "Regulatory fine of $2B imposed by EU", "impact": "Stock dropped 8% on announcement"}}
]

If no negative events are known, return: []"""


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

    from datetime import datetime, timedelta
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

    # Log what we are sending (summary)
    msg_count = len(state["messages"])
    tool_results = [m for m in state["messages"] if m.get("role") == "tool"]
    if tool_results:
        logger.info(
            f"Agent round {state['round_count']+1}: "
            f"sending {msg_count} messages ({len(tool_results)} tool results) to LLM"
        )

    try:
        from llm import invoke_llm
        response = invoke_llm(
            api_url=url,
            api_key=key,
            model=model,
            messages=state["messages"],
            tools=tools if tools else None,
            temperature=0.3,
            max_tokens=800,
            timeout=60.0,
        )
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        state["llm_response_raw"] = json.dumps({
            "sentiment": "neutral",
            "confidence_score": 0.0,
            "reasoning": f"LLM API call failed: {e}",
        }, ensure_ascii=False)
        return state

    tool_calls = getattr(response, "tool_calls", None)

    if tool_calls:
        # LLM wants tools — convert to OpenAI dict format and append
        openai_tool_calls = [
            {
                "id": tc.get("id", tc.get("name", "")),
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["args"] if isinstance(tc["args"], str) else json.dumps(tc["args"]),
                },
            }
            for tc in tool_calls
        ]
        state["messages"].append({
            "role": "assistant",
            "content": getattr(response, "content", None),
            "tool_calls": openai_tool_calls,
        })
        logger.info(
            f"Agent round {state['round_count']+1}: "
            f"LLM requested {len(tool_calls)} tool call(s)"
        )
    else:
        # Plain text response — analysis complete
        state["llm_response_raw"] = getattr(response, "content", "")
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
    """Execute an MCP tool by name. Returns result dict or error string.

    Tries to auto-reconnect if the MCP client is unavailable.
    """
    try:
        from mcp_client import get_mcp_client, init_mcp_client
        mcp = get_mcp_client()
        if mcp is None:
            # Try to initialize from DB config
            mcp_url = db.get_config("mcp_server_url") or "" if db else ""
            if mcp_url:
                logger.info(f"Attempting lazy MCP connect to {mcp_url}")
                if init_mcp_client(mcp_url):
                    mcp = get_mcp_client()
            if mcp is None:
                return {"error": "MCP client not connected — is the MCP server running?"}

        result = mcp.call_tool(name, arguments)
        if result is None:
            # call_tool already tried reconnect — give up
            return {"error": f"Tool {name} returned no data — MCP server may be unreachable"}
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
    graph.add_node("fetch_news_context", fetch_news_context)
    graph.add_node("agent_node", agent_node)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("parse_response", parse_response)
    graph.add_node("evaluate_trade", evaluate_trade)

    graph.set_entry_point("receive_news")
    graph.add_edge("receive_news", "build_prompt")
    graph.add_edge("build_prompt", "fetch_news_context")
    graph.add_edge("fetch_news_context", "agent_node")

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
    """Extract ALL LLM conversation messages as a flat chat log.

    Returns a list of messages, each with role, label and content.
    No grouping — every message is shown individually.
    """
    messages = state.get("messages", [])
    result: list[dict] = []

    if not messages:
        # Fallback: single prompt/response pair
        prompt = state.get("prompt", "")
        response = state.get("llm_response_raw", "")
        if prompt:
            result.append({"role": "user", "label": "User Message (News)", "content": prompt})
        if response:
            result.append({"role": "assistant", "label": "LLM Final Response", "content": response})
        return result

    context_appended = False  # only insert news context once
    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            result.append({
                "role": "system",
                "label": "System Prompt",
                "content": msg.get("content", ""),
            })

        elif role == "user":
            result.append({
                "role": "user",
                "label": "User Message (News)",
                "content": msg.get("content", ""),
            })
            # Insert news context once, right after the first user message
            if not context_appended:
                context_appended = True
                pos_ctx = state.get("positive_news_context", "")
                neg_ctx = state.get("negative_news_context", "")
                if pos_ctx and pos_ctx.strip() and pos_ctx.strip() != "[]":
                    result.append({
                        "role": "tool",
                        "label": "Context LLM → Positive News (6 months)",
                        "content": pos_ctx,
                    })
                if neg_ctx and neg_ctx.strip() and neg_ctx.strip() != "[]":
                    result.append({
                        "role": "tool",
                        "label": "Context LLM → Negative News (6 months)",
                        "content": neg_ctx,
                    })

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                result.append({
                    "role": "assistant",
                    "label": f"LLM → Tool Call ({len(tool_calls)} tool{'s' if len(tool_calls)>1 else ''})",
                    "content": _format_tool_calls(tool_calls),
                })
            else:
                result.append({
                    "role": "assistant",
                    "label": "LLM Final Response",
                    "content": msg.get("content", ""),
                })

        elif role == "tool":
            tool_id = msg.get("tool_call_id", "?")[:12]
            result.append({
                "role": "tool",
                "label": f"Tool Result [{tool_id}]",
                "content": msg.get("content", ""),
            })

    return result


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
        "context_llm_url": "",
        "context_llm_key": "",
        "context_llm_model": "",
        "positive_news_context": "",
        "negative_news_context": "",
        "trade_action": "",
    }
    result = workflow.invoke(initial_state)
    return result
