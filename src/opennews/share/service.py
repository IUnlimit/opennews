"""分享图片数据构建服务。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from opennews.config import settings
from opennews import db

logger = logging.getLogger(__name__)


def build_share_data(
    hours: float | None = None,
    score_lo: float | None = None,
    score_hi: float | None = None,
    lang: str | None = None,
    limit: int | None = None,
) -> dict:
    """构建分享图所需的完整数据模型。"""
    hours = hours if hours is not None else settings.share_default_hours
    score_lo = score_lo if score_lo is not None else settings.share_default_score_lo
    score_hi = score_hi if score_hi is not None else settings.share_default_score_hi
    lang = lang or settings.share_default_lang
    limit = limit if limit is not None else settings.share_default_limit

    snapshot = db.get_share_snapshot_data(
        hours=hours,
        score_lo=score_lo,
        score_hi=score_hi,
        limit=limit,
    )

    total = snapshot["total_items"]
    filtered = snapshot["filtered_count"]
    ratio = (filtered / total * 100) if total > 0 else 0

    # 时间范围文本
    if lang == "zh":
        if hours < 24:
            scope_text = f"最近 {hours:.0f} 小时"
        elif hours % 24 == 0:
            scope_text = f"最近 {hours / 24:.0f} 天"
        else:
            scope_text = f"最近 {hours:.0f} 小时"
    else:
        if hours < 24:
            scope_text = f"Last {hours:.0f} hour{'s' if hours != 1 else ''}"
        elif hours % 24 == 0:
            days = hours / 24
            scope_text = f"Last {days:.0f} day{'s' if days != 1 else ''}"
        else:
            scope_text = f"Last {hours:.0f} hours"

    now = datetime.now(timezone.utc)

    # 提取 top items 的精简信息
    top_news = []
    for item in snapshot["top_items"]:
        news = item.get("news") or {}
        report = item.get("report") or {}
        clf = item.get("classification") or {}
        top_news.append({
            "title": news.get("title", ""),
            "score": report.get("final_score", 0),
            "level": report.get("impact_level", "低"),
            "category": clf.get("category", "unknown"),
            "source": news.get("source", ""),
            "published_at": news.get("published_at", ""),
        })

    return {
        "lang": lang,
        "generated_at": now.isoformat(),
        "scope_text": scope_text,
        "score_range": f"{score_lo:.0f}–{score_hi:.0f}",
        "total_items": total,
        "filtered_count": filtered,
        "filtered_ratio": round(ratio, 1),
        "above75": snapshot["above75"],
        "levels": snapshot["levels"],
        "filtered_levels": snapshot["filtered_levels"],
        "top_news": top_news,
    }
