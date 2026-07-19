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
from database import Database
from rabbitmq_consumer import MQConsumer
from trading_engine import MockTradingEngine
from sse_manager import SSEManager
import services

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# These are injected by main.py on startup
sse_manager: SSEManager
trading_engine: MockTradingEngine
mq_consumer: MQConsumer
db: Database
def init(sse: SSEManager, trader: MockTradingEngine, mq: MQConsumer, db_instance: Database):
    global sse_manager, trading_engine, mq_consumer, db
    sse_manager = sse
    trading_engine = trader
    mq_consumer = mq
    db = db_instance


#
# Health
#

@router.get("/health")
def get_health() -> HealthStatus:
    rmq = mq_consumer.is_connected()
    llm_configured = bool(db.get_config("llm_api_url"))
    enabled = db.get_config("llm_enabled")
    llm_enabled = enabled != "false" if enabled is not None else True
    db_ok = True
    try:
        db.get_db().execute("SELECT 1")
    except Exception:
        db_ok = False
    # Check MCP client status
    mcp_ok = False
    try:
        import mcp_client
        mcp_ok = mcp_client.get_mcp_client() is not None
    except Exception:
        pass
    mq_listening = mq_consumer.is_listening()
    return HealthStatus(
        rabbitmq=rmq,
        database=db_ok,
        llm_configured=llm_configured,
        llm_enabled=llm_enabled,
        mcp_connected=mcp_ok,
        mq_listening=mq_listening,
    )


#
# MQ Control — start/stop RabbitMQ consumption
#

@router.post("/mq/start")
def mq_start() -> dict:
    """Enable RabbitMQ message consumption."""
    mq_consumer.start()
    return {"listening": True}


@router.post("/mq/stop")
def mq_stop() -> dict:
    """Disable RabbitMQ message consumption (pause without disconnect)."""
    mq_consumer.stop()
    return {"listening": False}


#
# Config
#

def _mask_key(key: str) -> str:
    return key[:4] + "****" + key[-4:] if len(key) > 8 else "****"


@router.get("/config")
def get_config() -> ConfigResponse:
    url = db.get_config("llm_api_url") or ""
    key = db.get_config("llm_api_key") or ""
    model = db.get_config("llm_model") or "gpt-4o"
    enabled = db.get_config("llm_enabled")
    llm_enabled = enabled != "false" if enabled is not None else True
    mcp_url = db.get_config("mcp_server_url") or ""
    ctx_url = db.get_config("context_llm_url") or ""
    ctx_key = db.get_config("context_llm_key") or ""
    ctx_model = db.get_config("context_llm_model") or ""
    return ConfigResponse(
        llm_api_url=url,
        llm_api_key_masked=_mask_key(key),
        llm_model=model,
        llm_enabled=llm_enabled,
        mcp_server_url=mcp_url,
        context_llm_url=ctx_url,
        context_llm_key_masked=_mask_key(ctx_key),
        context_llm_model=ctx_model,
    )


@router.put("/config")
def update_config(body: ConfigUpdate) -> ConfigResponse:
    db.set_config("llm_api_url", body.llm_api_url)
    db.set_config("llm_api_key", body.llm_api_key)
    db.set_config("llm_model", body.llm_model)
    db.set_config("llm_enabled", "true" if body.llm_enabled else "false")
    if body.mcp_server_url:
        db.set_config("mcp_server_url", body.mcp_server_url)
    if body.context_llm_url:
        db.set_config("context_llm_url", body.context_llm_url)
    if body.context_llm_key:
        db.set_config("context_llm_key", body.context_llm_key)
    if body.context_llm_model:
        db.set_config("context_llm_model", body.context_llm_model)
    # Re-initialize MCP client if URL changed
    _reinit_mcp(body.mcp_server_url)
    key = body.llm_api_key
    ctx_key = body.context_llm_key
    return ConfigResponse(
        llm_api_url=body.llm_api_url,
        llm_api_key_masked=_mask_key(key),
        llm_model=body.llm_model,
        llm_enabled=body.llm_enabled,
        mcp_server_url=body.mcp_server_url or (db.get_config("mcp_server_url") or ""),
        context_llm_url=body.context_llm_url or (db.get_config("context_llm_url") or ""),
        context_llm_key_masked=_mask_key(ctx_key),
        context_llm_model=body.context_llm_model or (db.get_config("context_llm_model") or ""),
    )


def _reinit_mcp(url: str):
    """Re-initialize the MCP client with a new URL."""
    if not url:
        return
    try:
        import mcp_client
        mcp_client.shutdown_mcp_client()
        ok = mcp_client.init_mcp_client(url)
        logger.info(f"MCP re-initialized: {url} — {'OK' if ok else 'FAILED'}")
    except Exception as e:
        logger.warning(f"MCP re-init failed: {e}")


@router.post("/config/toggle-llm")
def toggle_llm() -> dict:
    """Toggle LLM on/off.  When off the pipeline uses keyword-based
    fallback analysis instead of calling the configured LLM API."""
    current = db.get_config("llm_enabled")
    enabled = current != "false" if current is not None else True
    new_enabled = not enabled
    db.set_config("llm_enabled", "true" if new_enabled else "false")
    logger.info(f"LLM toggled {'ON' if new_enabled else 'OFF'}")
    return {"llm_enabled": new_enabled}


#
# News
#

@router.get("/news")
def list_news(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return {"news": db.list_news(limit, offset)}


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
    item = db.get_news(news_id)
    if not item:
        raise HTTPException(404, "News not found")
    return item


#
# Signals
#

@router.get("/signals")
def list_signals(limit: int = Query(100, ge=1, le=500)):
    return {"signals": db.list_sentiment_results(limit)}


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str):
    result = db.get_sentiment_result(signal_id)
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
