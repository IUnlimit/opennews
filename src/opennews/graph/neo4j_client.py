from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from neo4j import GraphDatabase


@dataclass(slots=True)
class GraphPayload:
    news: dict
    entities: list[dict]
    topic: dict
    impacts: list[dict]
    # Step2: 分类 & 特征（可选）
    classification: dict | None = None
    features: dict | None = None
    # Step4: 最终影响评分（可选）
    report: dict | None = None


class Neo4jGraphClient:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    @contextmanager
    def session(self):
        s = self.driver.session()
        try:
            yield s
        finally:
            s.close()

    def ensure_schema(self) -> None:
        stmts = [
            "CREATE CONSTRAINT news_id IF NOT EXISTS FOR (n:News) REQUIRE n.news_id IS UNIQUE",
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
            "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE",
        ]
        with self.session() as s:
            for stmt in stmts:
                s.run(stmt)

    def upsert_batch(self, payloads: Iterable[GraphPayload]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.session() as s:
            for payload in payloads:
                news = payload.news
                topic = payload.topic
                s.run(
                    """
                    MERGE (n:News {news_id: $news_id})
                    SET n.title=$title, n.content=$content, n.source=$source,
                        n.url=$url, n.published_at=$published_at,
                        n.embedding=$embedding, n.updated_at=$now,
                        n.category=$category, n.category_confidence=$category_confidence,
                        n.impact_score=$impact_score, n.features=$features,
                        n.final_impact_score=$final_impact_score,
                        n.impact_level=$impact_level
                    MERGE (t:Topic {topic_id: $topic_id})
                    SET t.label_zh=$topic_label_zh, t.label_en=$topic_label_en, t.updated_at=$now
                    MERGE (n)-[r:IN_TOPIC]->(t)
                    SET r.prob=$topic_prob, r.updated_at=$now
                    """,
                    {
                        "news_id": news["news_id"],
                        "title": news["title"],
                        "content": news["content"],
                        "source": news["source"],
                        "url": news["url"],
                        "published_at": news["published_at"],
                        "embedding": news["embedding"],
                        "topic_id": topic["topic_id"],
                        "topic_label_zh": topic["label"].get("zh", "") if isinstance(topic["label"], dict) else topic["label"],
                        "topic_label_en": topic["label"].get("en", "") if isinstance(topic["label"], dict) else topic["label"],
                        "topic_prob": topic["probability"],
                        # Step2: 分类 & 特征
                        "category": (payload.classification or {}).get("category", "unknown"),
                        "category_confidence": (payload.classification or {}).get("confidence", 0.0),
                        "impact_score": (payload.features or {}).get("impact_score", 0.0),
                        "features": json.dumps(payload.features) if payload.features else "{}",
                        # Step4: 最终影响评分
                        "final_impact_score": (payload.report or {}).get("final_score", 0.0),
                        "impact_level": (payload.report or {}).get("impact_level", ""),
                        "now": now,
                    },
                )

                for ent in payload.entities:
                    s.run(
                        """
                        MERGE (e:Entity {entity_id: $entity_id})
                        SET e.name=$name, e.type=$type, e.updated_at=$now
                        WITH e
                        MATCH (n:News {news_id: $news_id})
                        MERGE (n)-[m:MENTIONS]->(e)
                        SET m.confidence=$confidence, m.updated_at=$now
                        """,
                        {
                            "entity_id": ent["entity_id"],
                            "name": ent["name"],
                            "type": ent["type"],
                            "confidence": ent["confidence"],
                            "news_id": news["news_id"],
                            "now": now,
                        },
                    )

                for imp in payload.impacts:
                    s.run(
                        """
                        MERGE (e1:Entity {entity_id: $src})
                        MERGE (e2:Entity {entity_id: $dst})
                        MERGE (e1)-[r:IMPACTS]->(e2)
                        SET r.weight=$weight, r.method='cosine_v1', r.updated_at=$now
                        """,
                        {
                            "src": imp["src"],
                            "dst": imp["dst"],
                            "weight": imp["weight"],
                            "now": now,
                        },
                    )
