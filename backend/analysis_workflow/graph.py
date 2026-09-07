"""LangGraph workflow graph topology assembly.

Pipeline:
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

from langgraph.graph import StateGraph, END

from .state import AnalysisState

from .nodes.setup import receive_news
from .nodes.news_classifier import classify_news, route_after_classify
from .nodes.stock_identification import identify_stock, route_after_identify
from .nodes.skip import skip_to_end
from .nodes.prompt_building import build_prompt
from .nodes.news_context import fetch_news_context
from .nodes.agent_loop import agent_node, execute_tools, should_continue
from .nodes.output import parse_response, evaluate_trade


def build_workflow() -> StateGraph:
    """Construct and compile the LangGraph StateGraph."""
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
