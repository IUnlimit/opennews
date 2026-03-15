from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from itertools import combinations

import numpy as np

from opennews.ingest.news_fetcher import NewsItem
from opennews.nlp.entity_extractor import EntityMention
from opennews.topic.online_topic_model import TopicAssignment


def _entity_id(name: str, label: str) -> str:
    raw = f"{name.lower()}|{label}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_graph_payload(
    item: NewsItem,
    embedding: list[float],
    entities: list[EntityMention],
    topic: TopicAssignment,
    topic_label: dict[str, str],
    now_utc: datetime | None = None,
) -> dict:
    entity_dicts = [
        {
            "entity_id": _entity_id(e.text, e.label),
            "name": e.text,
            "type": e.label,
            "confidence": e.score,
        }
        for e in entities
        if e.text
    ]

    now = now_utc or datetime.now(timezone.utc)
    delta_hours = max((now - item.published_at).total_seconds() / 3600.0, 0.0)
    time_decay = float(np.exp(-delta_hours / 24.0))
    impacts = []
    for a, b in combinations(entity_dicts, 2):
        # 影响权重 = 语义自相似(=1.0) * 时间衰减（Step1 基线）
        w = max(0.05, min(1.0, 1.0 * time_decay))
        impacts.append({"src": a["entity_id"], "dst": b["entity_id"], "weight": w})
        impacts.append({"src": b["entity_id"], "dst": a["entity_id"], "weight": w})

    return {
        "news": {
            "news_id": item.news_id,
            "title": item.title,
            "content": item.content,
            "source": item.source,
            "url": item.url,
            "published_at": item.published_at.isoformat(),
            "embedding": embedding,
        },
        "entities": entity_dicts,
        "topic": {
            "topic_id": topic.topic_id,
            "probability": topic.probability,
            "label": topic_label,
        },
        "impacts": impacts,
    }
