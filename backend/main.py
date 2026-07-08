"""FastAPI application — defines the ASGI app.  Run with ``uvicorn main:app``."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dispatcher import Dispatcher
import rabbitmq_consumer
from sse_manager import SSEManager
from trading_engine import MockTradingEngine
import services
import api_routes
import queue
import mcp_client
import config
from database import Database
from logging_config import setup_logging

setup_logging("backend")
logger = logging.getLogger(f"backend.{__name__}")

#
# Globals
#
sse_message_queue = asyncio.Queue()
in_message_queue = queue.Queue()
sse_manager = SSEManager()

#
# Closure functions
async def sse_queue_process():
    while True:
        event_type, data = await sse_message_queue.get()
        await sse_manager.broadcast(event_type, data)

#
# Lifespan
#
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    db = Database()
    db.create_schema()
    trading_engine = MockTradingEngine(db)
    mq_consumer = rabbitmq_consumer.MQConsumer(in_message_queue)
    service_context = services.ServiceContext.create()
    service_provider = services.ServiceProvider(service_context)

    main_evet_loop = asyncio.get_event_loop()
    def sse_queue_put(event_type: str, data: dict):
        main_evet_loop.call_soon_threadsafe(sse_message_queue.put_nowait, (event_type, data))
    dispatcher = Dispatcher(in_message_queue, service_provider, sse_queue_put)

    # Startup
    logger.info("Starting Stock Trading Agent backend...")

    # Initialize MCP client for financial data enrichment
    mcp_ok = mcp_client.init_mcp_client(config.MCP_SERVER_URL)
    logger.info(f"MCP client: {'connected' if mcp_ok else 'unavailable (financial enrichment disabled)'}")

    # Inject dependencies
    api_routes.init(sse_manager, trading_engine, mq_consumer, db)

    # Start daemon threads
    mq_consumer_thread = asyncio.create_task(asyncio.to_thread(mq_consumer.run))
    dispatcher_thread = asyncio.create_task(asyncio.to_thread(dispatcher.run))

    # Start SSE queue processor
    sse_task = asyncio.create_task(sse_queue_process())

    logger.info("Backend ready.")

    yield

    # Shutdown
    logger.info("Shutting down...")
    mq_consumer.stop()
    dispatcher.stop()

    await mq_consumer_thread
    await dispatcher_thread
    
    sse_task.cancel()
    await sse_task
    mcp_client.shutdown_mcp_client()
    db.close()
    logger.info("Shutdown complete.")



#
# App
#

app = FastAPI(
    title="Stock Trading Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_routes.router)


#
# Health check root
#

@app.get("/")
def root():
    return {"service": "Stock Trading Agent", "version": "0.1.0"}
