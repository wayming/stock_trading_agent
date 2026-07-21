"""Keyword-based sentiment fallback — used when no LLM API is configured.

This module is intentionally kept separate from the LangGraph workflow so the
keyword rules can be maintained independently.
"""

import json

from models import SentimentLevel

SUPER_BULLISH_KEYWORDS = [
    "暴涨", "涨停", "翻倍", "重大利好", "远超预期", "超级利好",
    "历史新高", "获得重大合同", "突破性进展", "重磅",
    "soar", "skyrocket", "breakthrough", "record high",
]

BULLISH_KEYWORDS = [
    "上涨", "增长", "利好", "盈利", "扩大", "上升", "向好",
    "超出预期", "回购", "增持", "分红", "扩产",
    "growth", "profit", "beat", "exceed", "upgrade",
]

BEARISH_KEYWORDS = [
    "下跌", "下滑", "下降", "利空", "亏损", "减少", "萎缩",
    "低于预期", "减持", "裁员", "抛售",
    "decline", "loss", "miss", "downgrade", "drop",
]

SUPER_BEARISH_KEYWORDS = [
    "暴跌", "跌停", "崩盘", "破产", "退市", "暴雷", "造假",
    "重大利空", "腰斩", "严重亏损", "危机", "调查", "处罚",
    "crash", "bankruptcy", "fraud", "scandal", "collapse",
]


def classify(news_content: str) -> str:
    """Simple keyword-based sentiment classification when no LLM is configured.

    Args:
        news_content: The raw news text.

    Returns:
        A JSON string with sentiment, confidence_score, reasoning, and
        selected_symbol fields — matching the shape the workflow expects
        from an LLM response.
    """
    if not news_content:
        return json.dumps({
            "sentiment": SentimentLevel.NEUTRAL.value,
            "confidence_score": 0.4,
            "reasoning": "No news content provided.",
            "selected_symbol": "",
        }, ensure_ascii=False)

    content_lower = news_content.lower()

    super_bullish = sum(1 for kw in SUPER_BULLISH_KEYWORDS if kw in news_content or kw.lower() in content_lower)
    bullish = sum(1 for kw in BULLISH_KEYWORDS if kw in news_content or kw.lower() in content_lower)
    bearish = sum(1 for kw in BEARISH_KEYWORDS if kw in news_content or kw.lower() in content_lower)
    super_bearish = sum(1 for kw in SUPER_BEARISH_KEYWORDS if kw in news_content or kw.lower() in content_lower)

    scores = {
        SentimentLevel.SUPER_BULLISH.value: super_bullish * 3,
        SentimentLevel.BULLISH.value: bullish,
        SentimentLevel.BEARISH.value: bearish,
        SentimentLevel.SUPER_BEARISH.value: super_bearish * 3,
    }
    max_sentiment = max(scores, key=scores.get)
    max_score = scores[max_sentiment]

    if max_score == 0:
        sentiment = SentimentLevel.NEUTRAL.value
        confidence = 0.4
        reasoning = "No clear sentiment keywords detected in the news content."
    else:
        sentiment = max_sentiment
        confidence = min(0.9, 0.5 + max_score * 0.1)
        keywords_found = [kw for kw in (
            SUPER_BULLISH_KEYWORDS + BULLISH_KEYWORDS +
            BEARISH_KEYWORDS + SUPER_BEARISH_KEYWORDS
        ) if kw in news_content or kw.lower() in content_lower]
        reasoning = (
            f"Keyword-based analysis (LLM not configured). "
            f"Matched keywords: {', '.join(keywords_found[:10])}. "
            f"Sentiment: {sentiment}."
        )

    return json.dumps({
        "sentiment": sentiment,
        "confidence_score": round(confidence, 2),
        "reasoning": reasoning,
        "selected_symbol": "",
    }, ensure_ascii=False)
