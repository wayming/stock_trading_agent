"""Conversation extraction — converts AnalysisState into a human-readable chat log.

This module is purely about display formatting. It has no business logic
and no dependency on the graph topology or LLM invocation.
"""

from .state import AnalysisState


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
