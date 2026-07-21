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
import keyword_fallback
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


SYSTEM_PROMPT = """You are a professional stock market analyst for a LONG-ONLY stock trading system.

Your task is to analyze the expected impact of a news article and identify the best stock to BUY.

Assume the news is true. Do NOT verify whether the event actually happened. Analyze only the expected market impact.

## Input

Exchange: {{exchange}}
Stock Symbol: {{symbol}}
News Source: {{source}}

Content:
{{content}}

## Available tools

You have access to financial data tools:
- list_metrics: list available financial metrics
- get_data_period: check date range of available data
- get_financials: fetch revenue, profit, EPS, PE, PB, margins, etc.

---

## Exchange detection rules

When calling tools, supply the correct exchange code:

| Symbol pattern | Exchange | Examples |
|---|---|---|
| Pure digits, ≤5 chars | HKG | 0700, 6800, 0001 |
| Pure digits, 6 chars starting with 6 | SHA | 600519 |
| Pure digits, 6 chars starting with 0/3 | SHE | 302132 |
| Pure digits, 6 chars starting with 9 | SHA | 900948 |
| 3 uppercase letters | ASX | TCL, BHP, MGX |
| 1-5 uppercase letters (US) | NASDAQ | VSA, AAPL, TSLA |
| 1-5 uppercase letters (US) | NYSE | ZWS, GE, F |

If the symbol contains an exchange prefix like "NASDAQ:WYNN" or "ASX:TCL", parse out the exchange and code separately.

If a tool returns "no data found", try another exchange before giving up.

---

# Analysis Rules

Sentiment represents the expected stock price impact over the next **1–5 trading days**, NOT long-term intrinsic value.

Always analyze the impact on company earnings first, then infer the likely stock price reaction.

Financial fundamentals should strengthen or weaken your confidence, rather than replace the news analysis.

---
# Decision Flow

Stock Symbol is provided.

1. MUST call get_financials.
2. Analyze ONLY this company.
3. Combine:
   - News impact
   - Business exposure
   - Latest financial data
4. Generate the final sentiment.

## Financial Analysis

When financial data is available, consider:

- Revenue growth
- Net profit growth
- EPS trend
- PE valuation
- PB valuation
- Profit margins
- ROE
- Debt
- Cash flow

Do NOT simply list these metrics.

Explain whether they strengthen or weaken the expected news impact.

If financial data cannot be retrieved, continue using only the news and state that financial data was unavailable.

---

## Confidence Guidelines

0.90–1.00

- Direct company-specific news
- Financial data supports the conclusion

0.75–0.90

- Clear first-order industry impact
- Financials available

0.50–0.75

- Macro or indirect impact

Below 0.50

- Insufficient information
- Mixed signals
- Weak linkage

---

## Sentiment Scale

超级利好

Major positive catalyst likely to produce a strong upward stock move.

Examples:

- Major policy support
- Large contract
- Breakthrough product
- Significant earnings improvement

普通利好

Moderately positive news expected to improve earnings or sentiment.

neutral

No meaningful BUY opportunity.

普通利空

Moderately negative.

超级利空

Severely negative.

---

## Translation

Translate the news into fluent Chinese.

The translation must faithfully preserve the original meaning.

Do NOT summarize.

---

## Output

Return ONLY a valid JSON object.

Do NOT output Markdown.

Do NOT output explanations.

Do NOT output comments.

The JSON schema is:

{
  "sentiment": "超级利好 | 普通利好 | neutral | 普通利空 | 超级利空",
  "confidence_score": 0.00,
  "reasoning": "2-4 Chinese sentences explaining the judgement. Mention financial data if available.",
  "translate": "Chinese translation of the news.",
  "selected_symbol": "Stock code and company name, or empty string."
}
"""

IDENTIFY_STOCK_SYSTEM_PROMPT = """You are a professional stock market analyst for a LONG-ONLY stock trading system.

Your task is to identify the SINGLE BEST stock to BUY on the given exchange, based on the news provided.

## Rules

1. Identify industries expected to BENEFIT from the news.

2. Ignore industries whose primary impact is negative.

3. Among all beneficiary industries, choose the company that satisfies:

   - Most direct first-order earnings benefit
   - Largest market capitalization
   - Highest trading liquidity

4. Return ONLY a valid JSON object.

Do NOT output Markdown. Do NOT output explanations. Do NOT output comments.

If NO listed company on the specified exchange is expected to receive a meaningful positive impact, return empty strings.

## Output JSON schema

{
  "symbol": "Stock ticker code only (e.g., 0700, AAPL, TCL)",
  "company_name": "Full company name",
  "exchange": "Exchange code (HKG, SHA, SHE, ASX, NASDAQ, NYSE)",
  "reasoning": "1-2 sentences explaining why this stock was selected"
}

## Exchange codes

| Symbol pattern | Exchange | Examples |
|---|---|---|
| Pure digits, ≤5 chars | HKG | 0700, 6800, 0001 |
| Pure digits, 6 chars starting with 6 | SHA | 600519 |
| Pure digits, 6 chars starting with 0/3 | SHE | 302132 |
| Pure digits, 6 chars starting with 9 | SHA | 900948 |
| 3 uppercase letters | ASX | TCL, BHP, MGX |
| 1-5 uppercase letters (US) | NASDAQ | VSA, AAPL, TSLA |
| 1-5 uppercase letters (US) | NYSE | ZWS, GE, F |
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


#
# News classification — use flash model to categorize news before analysis
#

NEWS_CLASSIFY_SYSTEM_PROMPT = """You are a financial news classifier. Categorize the news into one of four types.

## Categories

### Noise
Stock price movements, market recaps, trading summaries.
- "X stock surged/dropped X% today"
- "Market rallied on optimism"
- Price milestones (all-time highs/lows)
→ IGNORE — no further analysis needed.

### Company
Company-specific news with direct earnings impact for a SPECIFIC company.
- Earnings reports, contract wins, product launches, M&A, management changes
- Regulatory actions targeting a specific company
→ CONTINUE analysis for this company.

### Industry
Industry-wide or sector-wide news that benefits/harms an entire sector.
- "Government announces solar subsidy program"
- "New regulations for the banking sector"
- "Chip export restrictions"
→ CONTINUE — identify the best stock in the affected industry.

### Macro
Macroeconomic, monetary policy, geopolitical, or broad market sentiment news.
- Interest rate decisions, GDP data, employment reports
- Geopolitical events (trade wars, conflicts)
- Monetary policy changes, inflation data
- Broad market sentiment without specific company/industry impact
→ IGNORE — no listed company receives a clear first-order earnings benefit.

## Key rule

Only select a stock if the news creates a clear first-order earnings benefit for one or more listed companies on the specified exchange. If the news is primarily macroeconomic, monetary policy, geopolitical, or broad market sentiment, and no listed company receives a clear first-order earnings benefit, return empty strings.

## Output

Return ONLY a valid JSON object:

{
  "category": "Noise | Company | Industry | Macro",
  "reason": "One short sentence in Chinese or English explaining the classification"
}
"""


def classify_news(state: AnalysisState) -> AnalysisState:
    """Use flash model to classify news before entering the main analysis pipeline.

    Categories:
      - Noise  → skip (price movement / market recap)
      - Macro  → skip (no clear first-order earnings benefit)
      - Company → continue (company-specific impact)
      - Industry → continue (sector-wide impact, stock identification needed)

    Falls back gracefully: if the LLM is unavailable, the news passes through.
    """
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
    state.setdefault("_pre_analysis_log", []).append({
        "step": "News Classification",
        "label": f"News Classification ({model})",
        "system_prompt": NEWS_CLASSIFY_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "response": raw,
    })

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


#
# Routing — decide next step after classification
#

def route_after_classify(state: AnalysisState) -> Literal["build_prompt", "identify_stock", "skip_to_end"]:
    """Route after classification: skip Noise/Macro, continue Company/Industry."""
    if state.get("_filtered"):
        return "skip_to_end"
    if state.get("news_symbol", "").strip():
        return "build_prompt"
    if state.get("news_exchange", "").strip():
        return "identify_stock"
    return "skip_to_end"


#
# Stock identification node — identify best stock when only exchange is given
#

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
    state.setdefault("_pre_analysis_log", []).append({
        "step": "Identify Stock",
        "label": f"Identify Stock ({model})",
        "system_prompt": IDENTIFY_STOCK_SYSTEM_PROMPT,
        "user_prompt": user_msg,
        "response": raw,
    })

    # Parse JSON from response
    import re as _re
    json_match = _re.search(r'\{[^{}]*\}', raw, _re.DOTALL)
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


def route_after_identify(state: AnalysisState) -> Literal["build_prompt", "skip_to_end"]:
    """After stock identification: continue if stock found, skip otherwise."""
    if state.get("_filtered"):
        return "skip_to_end"
    return "build_prompt"


#
# Fast path — neither symbol nor exchange provided
#

def skip_to_end(state: AnalysisState) -> AnalysisState:
    """Return neutral immediately — no LLM calls.

    Uses _filter_reason to produce a context-appropriate message.
    """
    reason = state.get("_filter_reason", "")
    exchange = state.get("news_exchange", "")

    if reason:
        # Classification or identification already provided the reason
        display_reason = reason
    elif not exchange:
        display_reason = "No stock symbol or exchange provided — insufficient information."
    else:
        display_reason = f"No actionable BUY opportunity identified on exchange {exchange}."

    logger.info(f"Skipping to end: {display_reason}")
    state["llm_response_raw"] = json.dumps({
        "sentiment": "neutral",
        "confidence_score": 0.3,
        "reasoning": display_reason,
        "selected_symbol": "",
    }, ensure_ascii=False)
    state["sentiment"] = "neutral"
    state["confidence_score"] = 0.3
    state["reasoning"] = display_reason
    state["selected_symbol"] = ""
    state["trade_action"] = "NONE"
    return state


def build_prompt(state: AnalysisState) -> AnalysisState:
    """Construct the initial prompt and initialise the conversation messages."""
    exchange = state.get("news_exchange", "")
    symbol = state.get("news_symbol", "")

    user_msg = f"Exchange: {exchange or 'N/A'}\n"
    user_msg += f"Stock Symbol: {symbol or 'N/A'}\n"
    user_msg += f"News Source: {state.get('news_source', 'unknown')}\n\n"
    user_msg += f"Content:\n{state.get('news_content', '')}"

    state["prompt"] = user_msg
    state["messages"] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    state["round_count"] = 0
    logger.debug(
        "Built prompt:\n=== SYSTEM ===\n%s\n=== USER ===\n%s\n=== END PROMPT ===",
        SYSTEM_PROMPT, user_msg,
    )
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
    state.setdefault("_pre_analysis_log", []).append({
        "step": "News Context (Positive)",
        "label": f"Context LLM → Positive News ({ctx_model})",
        "system_prompt": pos_prompt,
        "user_prompt": f"Search recent news for {symbol}",
        "response": pos_raw,
    })

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
    state.setdefault("_pre_analysis_log", []).append({
        "step": "News Context (Negative)",
        "label": f"Context LLM → Negative News ({ctx_model})",
        "system_prompt": neg_prompt,
        "user_prompt": f"Search recent news for {symbol}",
        "response": neg_raw,
    })

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
        state["llm_response_raw"] = keyword_fallback.classify(state.get("news_content", ""))
        return state

    tools = _get_tool_definitions()

    # Log the full system prompt + user message on first round
    msg_count = len(state["messages"])
    if state.get("round_count", 0) == 0:
        for m in state["messages"]:
            logger.debug(
                "LLM message [%s]:\n%s\n=== END %s ===",
                m.get("role", "?").upper(), m.get("content", ""), m.get("role", "?").upper(),
            )

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
    state["selected_symbol"] = str(parsed.get("selected_symbol", ""))
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
        receive_news → classify_news → route_after_classify ──→ build_prompt
                                                             ├─→ identify_stock
                                                             │     ↓
                                                             │   build_prompt
                                                             └─→ skip_to_end
                                                                    ↓
                                                              evaluate_trade → END

        build_prompt → fetch_news_context → agent_node
        agent_node → should_continue ──→ execute_tools → agent_node  (loop)
                                    └─→ parse_response  (exit)
        parse_response → evaluate_trade → END
    """
    graph = StateGraph(AnalysisState)

    graph.add_node("receive_news", receive_news)
    graph.add_node("classify_news", classify_news)
    graph.add_node("identify_stock", identify_stock)
    graph.add_node("skip_to_end", skip_to_end)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("fetch_news_context", fetch_news_context)
    graph.add_node("agent_node", agent_node)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("parse_response", parse_response)
    graph.add_node("evaluate_trade", evaluate_trade)

    graph.set_entry_point("receive_news")

    # receive_news → classify_news → route
    graph.add_edge("receive_news", "classify_news")
    graph.add_conditional_edges(
        "classify_news",
        route_after_classify,
        {
            "build_prompt": "build_prompt",
            "identify_stock": "identify_stock",
            "skip_to_end": "skip_to_end",
        },
    )

    # identify_stock → main pipeline, or skip if no stock found
    graph.add_conditional_edges(
        "identify_stock",
        route_after_identify,
        {"build_prompt": "build_prompt", "skip_to_end": "skip_to_end"},
    )

    # Main analysis pipeline
    graph.add_edge("build_prompt", "fetch_news_context")
    graph.add_edge("fetch_news_context", "agent_node")

    # Agent tool-calling loop
    graph.add_conditional_edges(
        "agent_node",
        should_continue,
        {"execute_tools": "execute_tools", "parse_response": "parse_response"},
    )
    graph.add_edge("execute_tools", "agent_node")

    # Final evaluation
    graph.add_edge("parse_response", "evaluate_trade")
    graph.add_edge("evaluate_trade", END)

    # Fast path (skip_to_end also goes through evaluate_trade for consistent trade_action)
    graph.add_edge("skip_to_end", "evaluate_trade")

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

    Includes pre-analysis LLM calls (news filter, stock identification,
    context news search) followed by the main agent/tool conversation.

    Returns a list of messages, each with role, label and content.
    No grouping — every message is shown individually.
    """
    messages = state.get("messages", [])
    result: list[dict] = []

    # ── Pre-analysis LLM calls (filter_news, identify_stock, fetch_news_context) ──
    pre_log = state.get("_pre_analysis_log", []) or []
    for entry in pre_log:
        step = entry.get("step", "Pre-analysis")
        label = entry.get("label", step)
        result.append({
            "role": "system",
            "label": f"[{step}] System Prompt",
            "content": entry.get("system_prompt", ""),
        })
        result.append({
            "role": "user",
            "label": f"[{step}] Request",
            "content": entry.get("user_prompt", ""),
        })
        result.append({
            "role": "assistant",
            "label": f"[{step}] Response",
            "content": entry.get("response", ""),
        })

    if not messages:
        # Fallback: single prompt/response pair (keyword mode or skip_to_end)
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
