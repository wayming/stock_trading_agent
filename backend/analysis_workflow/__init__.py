"""News sentiment analysis with MCP tool-calling — LangGraph workflow.

Pipeline graph:
  receive_news → classify_news → route_after_classify ──→ build_prompt
                                                        ├─→ identify_stock
                                                        │     ↓
                                                        │   build_prompt
                                                        └─→ skip_to_end
                                                               ↓
                                                         evaluate_trade → END

  build_prompt → fetch_news_context → agent_node ←→ execute_tools
                                          │ (no tool_calls)
                                          ↓
                                    parse_response → evaluate_trade → END

Public API:
  - run_analysis(news_item)  → AnalysisState
  - extract_conversation(state) → list[dict]
  - db singleton: inject via ``analysis_workflow.runner.db = my_db``
"""

from .runner import get_workflow, run_analysis
from .conversation import extract_conversation
from .state import AnalysisState

__all__ = [
    "run_analysis",
    "extract_conversation",
    "get_workflow",
    "AnalysisState",
]
