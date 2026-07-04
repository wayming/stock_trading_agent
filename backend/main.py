"""FastAPI application entry point for the Stock Trading Agent backend."""

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

#
# Logging
#

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

#
# Globals
#
sse_message_queue = asyncio.Queue()
in_message_queue = queue.Queue()
sse_manager = SSEManager()

#
# Closure functions
#
async def sse_queue_process():
    while True:
        event_type, data = await sse_message_queue.get()
        await sse_manager.broadcast(event_type, data)

def sse_queue_put(event_type: str, data: dict):
    asyncio.get_running_loop().call_soon_threadsafe(sse_message_queue.put_nowait, (event_type, data))


#
# Lifespan
#
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    trading_engine = MockTradingEngine()
    mq_consumer = rabbitmq_consumer.MQConsumer(in_message_queue)
    service_context = services.ServiceContext.create()
    service_provider = services.ServiceProvider(service_context)
    dispatcher = dispatcher.Dispatcher(in_message_queue, service_provider, sse_queue_put)

    # Startup
    logger.info("Starting Stock Trading Agent backend...")

    # Inject dependencies
    api_routes.init(sse_manager, trading_engine)

    # Start daemon threads
    mq_consumer_thread = asyncio.to_thread(mq_consumer.run)
    dispatcher_thread = asyncio.to_thread(dispatcher.run)

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


#
# Main
#

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
