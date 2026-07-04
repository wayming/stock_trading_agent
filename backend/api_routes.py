"""FastAPI routes — REST endpoints + SSE stream."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import json
import threading

from models import (
    ConfigUpdate,
    ConfigResponse,
    HealthStatus,
)
import database
import rabbitmq_consumer
import services
from trading_engine import MockTradingEngine
from sse_manager import SSEManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# These are injected by main.py on startup
sse_manager: SSEManager
trading_engine: MockTradingEngine


def init(sse: SSEManager, te: MockTradingEngine):
    global sse_manager, trading_engine
    sse_manager = sse
    trading_engine = te


#
# Health
#

@router.get("/health")
def get_health() -> HealthStatus:
    rmq = rabbitmq_consumer.is_connected()
    llm_configured = bool(database.get_config("llm_api_url"))
    db_ok = True
    try:
        database.get_db().execute("SELECT 1")
    except Exception:
        db_ok = False
    return HealthStatus(
        rabbitmq=rmq,
        database=db_ok,
        llm_configured=llm_configured,
    )


#
# Config
#

@router.get("/config")
def get_config() -> ConfigResponse:
    url = database.get_config("llm_api_url") or ""
    key = database.get_config("llm_api_key") or ""
    model = database.get_config("llm_model") or "gpt-4o"
    masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return ConfigResponse(
        llm_api_url=url,
        llm_api_key_masked=masked,
        llm_model=model,
    )


@router.put("/config")
def update_config(body: ConfigUpdate) -> ConfigResponse:
    database.set_config("llm_api_url", body.llm_api_url)
    database.set_config("llm_api_key", body.llm_api_key)
    database.set_config("llm_model", body.llm_model)
    key = body.llm_api_key
    masked = key[:4] + "****" + key[-4:] if len(key) > 8 else "****"
    return ConfigResponse(
        llm_api_url=body.llm_api_url,
        llm_api_key_masked=masked,
        llm_model=body.llm_model,
    )


#
# News
#

@router.get("/news")
def list_news(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return {"news": database.list_news(limit, offset)}


@router.post("/news")
def push_news(body: dict):
    """Direct news ingestion — bypass RabbitMQ for testing/ease of use."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    # Run processing in a thread to avoid blocking
    thread = threading.Thread(target=services.process_news_message, args=(raw,), daemon=True)
    thread.start()
    return {"status": "accepted", "content": body.get("content", "")[:80]}


@router.get("/news/{news_id}")
def get_news_item(news_id: str):
    item = database.get_news(news_id)
    if not item:
        raise HTTPException(404, "News not found")
    return item


#
# Signals
#

@router.get("/signals")
def list_signals(limit: int = Query(100, ge=1, le=500)):
    return {"signals": database.list_sentiment_results(limit)}


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str):
    result = database.get_sentiment_result(signal_id)
    if not result:
        raise HTTPException(404, "Signal not found")
    return result


#
# Positions & Trades
#

@router.get("/positions")
def list_positions():
    positions = trading_engine.get_positions()
    pnl = trading_engine.get_pnl_summary()
    return {"positions": positions, "pnl": pnl}


@router.get("/trades")
def list_trades(limit: int = Query(50, ge=1, le=500)):
    return {"trades": trading_engine.get_trade_history(limit)}


#
# SSE Stream
#

@router.get("/stream")
async def stream_events(request: Request):
    """SSE endpoint — pushes real-time signal, news, and analysis events."""
    queue = await sse_manager.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield message
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
        finally:
            sse_manager.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
