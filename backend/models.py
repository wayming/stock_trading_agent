"""Pydantic data models for the trading agent."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class SentimentLevel(str, Enum):
    SUPER_BULLISH = "超级利好"
    BULLISH = "普通利好"
    NEUTRAL = "neutral"
    BEARISH = "普通利空"
    SUPER_BEARISH = "超级利空"


class TradeAction(str, Enum):
    BUY = "BUY"
    SHORT = "SHORT"
    NONE = "NONE"


class NewsItem(BaseModel):
    id: str
    content: str
    source: str = ""
    symbol: str = ""
    timestamp: str = ""


class SentimentResult(BaseModel):
    id: str
    news_id: str
    sentiment: SentimentLevel
    confidence_score: float
    reasoning: str
    prompt: str
    llm_response: str
    trade_action: TradeAction = TradeAction.NONE
    timestamp: str = ""


class Trade(BaseModel):
    id: str
    news_id: str
    sentiment_result_id: str
    action: TradeAction
    symbol: str
    entry_price: float
    status: str = "OPEN"  # OPEN | CLOSED
    pnl: float = 0.0
    created_at: str = ""
    closed_at: Optional[str] = None


class Position(BaseModel):
    id: str
    symbol: str
    action: TradeAction
    entry_price: float
    created_at: str
    pnl: float


class ConfigUpdate(BaseModel):
    llm_api_url: str
    llm_api_key: str
    llm_model: str = "gpt-4o"
    llm_enabled: bool = True
    mcp_server_url: str = ""


class ConfigResponse(BaseModel):
    llm_api_url: str
    llm_api_key_masked: str
    llm_model: str
    llm_enabled: bool
    mcp_server_url: str


class HealthStatus(BaseModel):
    rabbitmq: bool
    database: bool
    llm_configured: bool
    llm_enabled: bool
    mcp_connected: bool
