#!/usr/bin/env python3
"""Standalone news stub — generates fake financial news and publishes to RabbitMQ.

Usage:
    python3 news_stub.py                          # one shot
    python3 news_stub.py --interval 5             # every 5 seconds
    python3 news_stub.py --count 20 --interval 2  # 20 messages, 2 s apart
    python3 news_stub.py --help
"""

import argparse
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone

#
# Config (mirrors config.py so this file is self-contained)
#

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "stock_news")

#
# Logging (configured in main() below)
#

logger = logging.getLogger("news_stub")

#
# News templates
#

SYMBOLS = ["AAPL", "TSLA", "NVDA", "GOOGL", "MSFT", "AMZN", "META", "BABA", "TSM", "JPM"]

TEMPLATES_ZH = [
    # 超级利好
    ("{symbol} 发布突破性AI芯片，性能超越行业标准3倍，股价盘后暴涨15%", "超级利好"),
    ("{symbol} 获得百亿美元级政府合同，分析师上调目标价至历史新高", "超级利好"),
    ("{symbol} 季度营收同比增长200%，远超华尔街预期，宣布1拆10股票分割", "超级利好"),
    # 普通利好
    ("{symbol} 扩大市场份额，Q3财报显示营收稳步增长12%，超出分析师预期", "普通利好"),
    ("{symbol} 宣布与行业龙头达成战略合作，拓展海外市场", "普通利好"),
    ("{symbol} 新产品线获得用户好评，预购订单超出预期30%", "普通利好"),
    ("{symbol} 宣布大规模股票回购计划，总金额达50亿美元", "普通利好"),
    # neutral
    ("{symbol} 举行年度股东大会，重申全年业绩指引，维持现有战略不变", "neutral"),
    ("{symbol} 高管变动：任命新任CTO，市场反应平淡", "neutral"),
    # 普通利空
    ("{symbol} Q3利润下滑8%，受原材料成本上升影响，下调全年毛利率预期", "普通利空"),
    ("{symbol} 面临欧盟反垄断调查，可能影响欧洲市场业务扩展", "普通利空"),
    ("{symbol} 遭机构投资者减持，大股东持股比例降至5%以下", "普通利空"),
    # 超级利空
    ("{symbol} 被曝财务造假，SEC启动正式调查，股价盘后暴跌20%", "超级利空"),
    ("{symbol} 核心产品出现重大安全漏洞，大规模召回导致预计亏损数十亿美元", "超级利空"),
    ("{symbol} CEO突然辞职并抛售全部持股，引发市场恐慌性抛售", "超级利空"),
]

TEMPLATES_EN = [
    ("{symbol} unveils breakthrough AI chip, 3× industry benchmark, shares surge 15% after-hours", "super_bullish"),
    ("{symbol} lands multi-billion government contract, analysts raise price target to all-time high", "super_bullish"),
    ("{symbol} Q3 revenue up 200% YoY, crushes estimates, announces 10-for-1 stock split", "super_bullish"),
    ("{symbol} expands market share with steady 12% revenue growth, beats consensus", "bullish"),
    ("{symbol} announces strategic partnership with industry leader for global expansion", "bullish"),
    ("{symbol} new product line drives 30% pre-order beat, positive user reviews", "bullish"),
    ("{symbol} initiates $5B share buyback program", "bullish"),
    ("{symbol} annual shareholder meeting reaffirms guidance, strategy unchanged", "neutral"),
    ("{symbol} appoints new CTO in executive reshuffle, market unmoved", "neutral"),
    ("{symbol} Q3 profit drops 8% on rising material costs, lowers gross margin outlook", "bearish"),
    ("{symbol} faces EU antitrust probe, European expansion at risk", "bearish"),
    ("{symbol} institutional investor reduces stake below 5% threshold", "bearish"),
    ("{symbol} accounting fraud allegations trigger SEC investigation, shares plunge 20%", "super_bearish"),
    ("{symbol} major product recall after safety flaw discovered, estimated multi-billion loss", "super_bearish"),
    ("{symbol} CEO resigns abruptly, sells entire stake, panic selling ensues", "super_bearish"),
]

SOURCES = ["Reuters", "Bloomberg", "CNBC", "Wall Street Journal", "Financial Times", "财联社", "东方财富", "雪球"]


#
# Generator
#

def generate_news(lang: str | None = None) -> dict:
    """Build a single random news item dict."""
    if lang is None:
        lang = random.choice(["zh", "en"])

    symbol = random.choice(SYMBOLS)
    if lang == "zh":
        template, sentiment = random.choice(TEMPLATES_ZH)
    else:
        template, sentiment = random.choice(TEMPLATES_EN)

    content = template.format(symbol=symbol)
    source = random.choice(SOURCES)
    news_id = str(uuid.uuid4())

    return {
        "id": news_id,
        "content": content,
        "source": source,
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


#
# RabbitMQ helpers
#

def _import_pika():
    """Lazy import so --help works without pika installed."""
    import pika
    from pika.exceptions import AMQPConnectionError
    return pika, AMQPConnectionError


def connect():
    pika, _ = _import_pika()
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        heartbeat=30,
        connection_attempts=3,
        retry_delay=2.0,
    )
    return pika.BlockingConnection(params)


def publish(channel, news_item: dict):
    body = json.dumps(news_item, ensure_ascii=False).encode("utf-8")
    channel.basic_publish(exchange="", routing_key=RABBITMQ_QUEUE, body=body)
    logger.info(
        "Published  id=%-36s  symbol=%-6s  content=%s",
        news_item["id"],
        news_item["symbol"],
        news_item["content"][:60],
    )


#
# Main
#

def main():
    parser = argparse.ArgumentParser(
        description="Generate fake financial news and publish to RabbitMQ.",
    )
    parser.add_argument(
        "--count", type=int, default=0,
        help="Number of messages to publish (0 = infinite, requires --interval)",
    )
    parser.add_argument(
        "--interval", type=float, default=0,
        help="Seconds between messages (default: 0 = fire once and exit)",
    )
    parser.add_argument(
        "--lang", choices=["zh", "en"], default=None,
        help="Language: zh (Chinese) or en (English). Omit for random mix.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print generated news to stdout instead of publishing to RabbitMQ.",
    )
    args = parser.parse_args()

    # DEBUG=1 env var controls level; setup once here
    from logging_config import setup_logging
    setup_logging("news_stub")

    # Validate
    if args.count == 0 and args.interval == 0:
        args.count = 1  # one-shot

    if args.dry_run:
        _run_dry(args)
    else:
        _run_live(args)


def _run_dry(args):
    """Print generated news to stdout — no RabbitMQ needed."""
    published = 0
    try:
        while True:
            news_item = generate_news(args.lang)
            print(json.dumps(news_item, ensure_ascii=False, indent=2))
            published += 1

            if args.count and published >= args.count:
                break
            if args.interval:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    logger.info("Dry-run done.  Generated %d message(s).", published)


def _run_live(args):
    """Connect to RabbitMQ and publish."""
    logger.info(
        "News stub starting  host=%s:%s  queue=%s  count=%s  interval=%ss  lang=%s",
        RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_QUEUE,
        args.count if args.count else "∞",
        args.interval,
        args.lang or "mixed",
    )

    try:
        conn = connect()
        channel = conn.channel()
        channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)
    except Exception as e:
        logger.error("Cannot connect to RabbitMQ at %s:%s — is it running?", RABBITMQ_HOST, RABBITMQ_PORT)
        logger.error("Start one with:  docker run -d --rm -p 5672:5672 rabbitmq:3-management")
        logger.error("Details: %s", e)
        raise SystemExit(1) from e

    published = 0
    try:
        while True:
            news_item = generate_news(args.lang)
            publish(channel, news_item)
            published += 1

            if args.count and published >= args.count:
                break
            if args.interval:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down.")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info("Done.  Published %d message(s).", published)


if __name__ == "__main__":
    main()
