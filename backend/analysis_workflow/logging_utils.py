"""Helpers for recording pre-analysis LLM calls (filter/identify/context)
into state for later display in the conversation view."""

from .state import AnalysisState


def log_llm_call(
    state: AnalysisState,
    step: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    response: str,
) -> None:
    """Append a pre-analysis LLM call record to the state's _pre_analysis_log."""
    state.setdefault("_pre_analysis_log", []).append({
        "step": step,
        "label": f"{step} ({model})",
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "response": response,
    })
