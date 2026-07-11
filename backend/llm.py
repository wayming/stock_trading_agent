"""Shared LLM helper — wraps LangChain ChatOpenAI for all LLM calls.

Replaces raw httpx + manual URL building with a single abstraction.
"""

import json
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

logger = logging.getLogger(f"backend.{__name__}")


def build_chat_model(api_url: str, api_key: str, model: str, **kwargs) -> ChatOpenAI:
    """Build a ChatOpenAI instance targeting any OpenAI-compatible endpoint.

    Args:
        api_url:  Base URL (e.g. https://api.deepseek.com).  /v1 is appended automatically.
        api_key:  API key.
        model:    Model name (e.g. deepseek-v4-pro, gpt-4o).
        **kwargs: Passed through to ChatOpenAI (temperature, max_tokens, etc.).
    """
    return ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        base_url=api_url.rstrip("/") + "/v1",   # LangChain appends /chat/completions
        **kwargs,
    )


def invoke_llm(
    api_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 800,
    timeout: float = 60.0,
) -> AIMessage:
    """Send messages to an LLM and return the AI response.

    Args:
        api_url:     Base URL of the OpenAI-compatible API.
        api_key:     API key.
        model:       Model name.
        messages:    List of {"role":..., "content":...} dicts.
        tools:       Optional OpenAI-format tool definitions.
        temperature, max_tokens, timeout:  LLM parameters.

    Returns:
        AIMessage — check .tool_calls and .content.
    """
    chat = build_chat_model(
        api_url, api_key, model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    lc_messages = _to_langchain_messages(messages)
    invoke_kwargs: dict = {}
    if tools:
        invoke_kwargs["tools"] = tools
        invoke_kwargs["tool_choice"] = "auto"

    response = chat.invoke(lc_messages, **invoke_kwargs)
    return response


def invoke_llm_simple(
    api_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 600,
    timeout: float = 30.0,
) -> str:
    """Simple single-turn LLM call — returns text content only.

    Used by fetch_news_context for positive/negative news queries.
    """
    chat = build_chat_model(
        api_url, api_key, model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    response = chat.invoke([
        SystemMessage(content=system_prompt or ""),
        HumanMessage(content=user_prompt or ""),
    ])
    return response.content if hasattr(response, "content") else str(response)


def lc_messages_to_dicts(lc_messages: list) -> list[dict]:
    """Convert LangChain message objects back to OpenAI-format dicts.

    Used when storing conversation history in state["messages"].
    """
    result = []
    for m in lc_messages:
        d = {"role": _role_to_str(m), "content": getattr(m, "content", None)}
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["args"] if isinstance(tc["args"], str) else json.dumps(tc["args"]),
                    },
                }
                for tc in tool_calls
            ]
        if d["role"] == "tool":
            d["tool_call_id"] = getattr(m, "tool_call_id", "")
        result.append(d)
    return result


# ── internal ──────────────────────────────────────────

def _role_to_str(msg) -> str:
    """Map LangChain message type to OpenAI role string."""
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, ToolMessage):
        return "tool"
    return "unknown"


def _to_langchain_messages(messages: list[dict]) -> list:
    """Convert OpenAI-format message dicts to LangChain message objects."""
    result = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content or ""))
        elif role == "user":
            result.append(HumanMessage(content=content or ""))
        elif role == "assistant":
            tool_calls = m.get("tool_calls")
            if tool_calls:
                # Convert OpenAI-format tool calls to LangChain format
                # OpenAI stores arguments as JSON string; LangChain expects dict
                lc_tool_calls = []
                for tc in tool_calls:
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    lc_tool_calls.append({
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "args": args,
                    })
                result.append(AIMessage(content=content or "", tool_calls=lc_tool_calls))
            else:
                result.append(AIMessage(content=content or ""))
        elif role == "tool":
            result.append(ToolMessage(content=content or "", tool_call_id=m.get("tool_call_id", "")))
    return result
