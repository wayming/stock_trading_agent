"""Environment-based configuration for the trading agent."""

import os

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "stock_news")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))

DB_PATH = os.getenv("DB_PATH", "data/trading_agent.db")

# Default LLM config — can be overridden via API
DEFAULT_LLM_API_URL = os.getenv("LLM_API_URL", "")
DEFAULT_LLM_API_KEY = os.getenv("LLM_API_KEY", "")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
