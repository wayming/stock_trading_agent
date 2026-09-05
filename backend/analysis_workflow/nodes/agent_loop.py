"""Nodes: agent_node, execute_tools, should_continue — the LLM ↔ tool-calling loop.

agent_node invokes the LLM with MCP tool definitions. If tool_calls are
returned, should_continue routes to execute_tools, which runs them via MCP
and loops back to agent_node — until a plain text response or MAX_TOOL_ROUNDS.
"""

import json
import logging

from ..state import AnalysisState
from ..tools.mcp_executor import get_tool_definitions, execute_mcp_tool

logger = logging.getLogger(f"backend.{__name__}")

MAX_TOOL_ROUNDS = 5


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
        import keyword_fallback
        state["llm_response_raw"] = keyword_fallback.classify(state.get("news_content", ""))
        return state

    tools = get_tool_definitions()

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
        result = execute_mcp_tool(name, args)
        logger.debug(f"Tool result: {result}")
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": json.dumps(result, ensure_ascii=False, default=str),
        })

    state["round_count"] = state.get("round_count", 0) + 1
    return state


def should_continue(state: AnalysisState):
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
