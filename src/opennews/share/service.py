"""分享图片数据构建服务。

输出结构与前端 web/src/types.ts 中 ShareData / ShareTopicItem 完全对齐，
以便后端 HTML 渲染器能生成与前端 ShareSnapshot.vue 视觉一致的截图。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from opennews.config import settings
from opennews import db

logger = logging.getLogger(__name__)


# ── 主题标签提取（与前端 getTopicLabel 对齐） ────────────
def _get_topic_label(topic: dict | None, lang: str) -> str:
    """从 topic payload 中提取指定语言的标签。"""
    if not topic:
        return "Unknown"
    label = topic.get("label")
    if label is None:
        return f"Topic {topic.get('topic_id', '?')}"
    if isinstance(label, dict):
        return label.get(lang) or label.get("zh") or label.get("en") or "Unknown"
    return str(label)


def build_share_data(
    hours: float | None = None,
    score_lo: float | None = None,
    score_hi: float | None = None,
    lang: str | None = None,
    limit: int | None = None,
) -> dict:
    """构建与前端 ShareData 同构的完整数据模型。

    返回字段（camelCase，与前端 TypeScript 接口一致）：
        lang, generatedAt, scopeText, scoreRange,
        totalItems, filteredCount, filteredRatio, above75,
        levels, filteredLevels, topTopics
    """
    hours = hours if hours is not None else settings.share_default_hours
    score_lo = score_lo if score_lo is not None else settings.share_default_score_lo
    score_hi = score_hi if score_hi is not None else settings.share_default_score_hi
    lang = lang or settings.share_default_lang
    limit = limit if limit is not None else settings.share_default_limit

    # 获取原始快照数据（含 top_items 列表）
    snapshot = db.get_share_snapshot_data(
        hours=hours,
        score_lo=score_lo,
        score_hi=score_hi,
        limit=9999,  # 取全部筛选结果，由本层做主题聚合
    )

    total = snapshot["total_items"]
    filtered = snapshot["filtered_count"]
    ratio = (filtered / total * 100) if total > 0 else 0

    # ── 时间范围文案（与前端 summaryScopeText 对齐） ──────
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

    # ── 主题聚合（与前端 App.vue shareData computed 对齐） ─
    topic_map: dict[str, dict] = {}
    for item in snapshot["top_items"]:
        topic = item.get("topic") or {}
        report = item.get("report") or {}
        tid = topic.get("topic_id", -1)
        bid = topic.get("batch_id", 0)
        key = f"{bid}:{tid}"
        score = report.get("final_score", 0)
        level = report.get("impact_level", "低")
        label_zh = _get_topic_label(topic, "zh")
        label_en = _get_topic_label(topic, "en")

        if key not in topic_map:
            topic_map[key] = {
                "labelZh": label_zh,
                "labelEn": label_en,
                "maxScore": score,
                "newsCount": 1,
                "topLevel": level,
            }
        else:
            t = topic_map[key]
            t["newsCount"] += 1
            if score > t["maxScore"]:
                t["maxScore"] = score
                t["topLevel"] = level

    top_topics = sorted(
        topic_map.values(),
        key=lambda t: t["maxScore"],
        reverse=True,
    )[:limit]

    return {
        "lang": lang,
        "generatedAt": now.isoformat(),
        "scopeText": scope_text,
        "scoreRange": f"{score_lo:.0f}\u2013{score_hi:.0f}",
        "totalItems": total,
        "filteredCount": filtered,
        "filteredRatio": round(ratio, 1),
        "above75": snapshot["above75"],
        "levels": snapshot["levels"],
        "filteredLevels": snapshot["filtered_levels"],
        "topTopics": top_topics,
    }
