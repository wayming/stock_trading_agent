"""Orchestration service — ties together consumer, workflow, DB, and SSE."""

import asyncio
import uuid
import json
import logging
from datetime import datetime, timezone

import database
import langgraph_workflow
from trading_engine import TradingEngine
from default_strategy import default_strategy
from sse_manager import SSEManager
from dataclasses import dataclass

logger = logging.getLogger(f"backend.{__name__}")

# Shared instances (set by main.py on startup)
sse_manager: SSEManager = None  # type: ignore
trading_engine: TradingEngine = None  # type: ignore
_main_loop: asyncio.AbstractEventLoop = None  # type: ignore


def set_main_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


@dataclass
class ServiceContext:
    database: database.Database
    trading_engine: TradingEngine

    @classmethod
    def create(cls):
        db = database.Database()
        return cls(
            database=db,
            trading_engine=TradingEngine(db, default_strategy),
        )

    @classmethod
    def destroy(cls):
        if cls.database:
            cls.database.close()

        cls.database = None
        cls.trading_engine = None

class ServiceProvider:
    def __init__(self, context: ServiceContext):
        self.context = context
        langgraph_workflow.db = self.context.database

    def run(self, body: bytes):
        """
        Process a news message from RabbitMQ.
        1. Parse JSON and store in DB
        2. Run LangGraph workflow
        3. Store sentiment result
        4. Evaluate trade signal
        """
        try:
            raw = body.decode("utf-8")
            news_dict = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to parse message: {e}")
            return

        news_id = news_dict.get("id") or str(uuid.uuid4())
        news_dict["id"] = news_id
        if "timestamp" not in news_dict or not news_dict["timestamp"]:
            news_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
        news_dict["raw_json"] = raw

        # Step 1: Persist news
        self.context.database.insert_news(news_dict)
        logger.info(f"[News {news_id}] Stored: {news_dict.get('content', '')[:80]}...")

        # Step 2: Run LangGraph pipeline
        state = langgraph_workflow.run_analysis(news_dict)
        logger.info(
            f"[News {news_id}] Analysis complete: sentiment={state['sentiment']}, "
            f"confidence={state['confidence_score']}, trade={state['trade_action']}"
        )

        # Step 3: Store sentiment result
        result_id = str(uuid.uuid4())
        conversation = langgraph_workflow.extract_conversation(state)
        sentiment_result = {
            "id": result_id,
            "news_id": news_id,
            "sentiment": state["sentiment"],
            "confidence_score": state["confidence_score"],
            "reasoning": state["reasoning"],
            "prompt": state["prompt"],
            "llm_response": state["llm_response_raw"],
            "conversation": json.dumps(conversation, ensure_ascii=False),
            "trade_action": state["trade_action"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.context.database.insert_sentiment_result(sentiment_result)

        # Step 4: Evaluate trade via strategy
        # Use user-provided symbol, or LLM-selected stock (Case B in prompt)
        effective_symbol = news_dict.get("symbol") or state.get("selected_symbol", "")
        trade = self.context.trading_engine.evaluate_signal(
            sentiment=state["sentiment"],
            confidence_score=state["confidence_score"],
            symbol=effective_symbol or "",
            news_id=news_id,
            sentiment_result_id=result_id,
        )

        # Step 5: Prepare broadcast payloads
        signal_payload = {
            "id": result_id,
            "news_id": news_id,
            "sentiment": state["sentiment"],
            "confidence_score": state["confidence_score"],
            "reasoning": state["reasoning"],
            "trade_action": state["trade_action"],
            "symbol": news_dict.get("symbol", ""),
            "timestamp": sentiment_result["timestamp"],
            "trade_id": trade["id"] if trade else None,
        }

        news_payload = {
            "id": news_id,
            "content": news_dict.get("content", ""),
            "source": news_dict.get("source", ""),
            "symbol": news_dict.get("symbol", ""),
            "timestamp": news_dict["timestamp"],
        }

        analysis_payload = {
            "id": result_id,
            "news_id": news_id,
            "prompt": state["prompt"],
            "llm_response": state["llm_response_raw"],
            "conversation": json.loads(sentiment_result["conversation"]),
            "sentiment": state["sentiment"],
            "confidence_score": state["confidence_score"],
            "reasoning": state["reasoning"],
            "timestamp": sentiment_result["timestamp"],
        }

        logger.info(f"[News {news_id}] Analysis complete")

        return [["signal", signal_payload], ["news", news_payload], ["analysis", analysis_payload]]

        # # Step 6: Broadcast via SSE on the main event loop
        # async def _broadcast():
        #     await sse_manager.broadcast("signal", signal_payload)
        #     await sse_manager.broadcast("news", news_payload)
        #     await sse_manager.broadcast("analysis", analysis_payload)

        # if _main_loop and _main_loop.is_running():
        #     asyncio.run_coroutine_threadsafe(_broadcast(), _main_loop)
        # else:
        #     # Fallback: run synchronously in a new loop (blocks the consumer briefly)
        #     try:
        #         asyncio.run(_broadcast())
        #     except RuntimeError:
        #         pass

