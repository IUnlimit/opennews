from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypedDict

from neo4j.exceptions import Neo4jError, ServiceUnavailable

logger = logging.getLogger(__name__)

from langgraph.graph import END, StateGraph

from opennews.agents.classifier_agent import ClassificationResult, ClassifierAgent
from opennews.agents.feature_agent import FeatureAgent, FeatureVector
from opennews.agents.memory_agent import MemoryAgent, TopicTrend
from opennews.agents.report_agent import NewsReport, ReportAgent
from opennews.config import settings
from opennews.db import ensure_schema as ensure_pg_schema, insert_batch, insert_reports
from opennews.graph.neo4j_client import GraphPayload, Neo4jGraphClient
from opennews.graph.subgraph_query import GraphRAGQuerier
from opennews.graph.upsert import build_graph_payload
from opennews.ingest.checkpoint import CheckpointStore
from opennews.ingest.news_fetcher import (
    NewsItem, deduplicate_news, fetch_newsnow,
)
from opennews.ingest.seed_injector import RealtimeSeedInjector
from opennews.ingest.sources import SourcesConfig
from opennews.memory import MemoryRecord, RedisMemoryStore
from opennews.nlp.embedder import TextEmbedder
from opennews.nlp.entity_extractor import EntityExtractor
from opennews.topic.online_topic_model import OnlineTopicModel
from opennews.agents.topic_refine_agent import TopicRefineAgent
from opennews.llm.client import LLMConfig


class PipelineState(TypedDict, total=False):
    news_batch: list[NewsItem]
    docs: list[str]
    embeddings: list[list[float]]
    entities: list[list]
    topics: list
    # Step2: 分类 & 特征
    classifications: list[ClassificationResult]
    features: list[FeatureVector]
    payloads: list[GraphPayload]
    # Step3: 时序记忆 & 趋势
    topic_trends: dict[int, TopicTrend]
    # Step4: 影响评估报告
    reports: list[NewsReport]
    result: str


@dataclass
class PipelineRuntime:
    embedder: TextEmbedder = field(default_factory=lambda: TextEmbedder(settings.embedding_model))
    extractor: EntityExtractor = field(default_factory=lambda: EntityExtractor(settings.ner_model))
    topic_model: OnlineTopicModel = field(
        default_factory=OnlineTopicModel
    )
    # LLM 主题精炼 Agent
    topic_refine_agent: TopicRefineAgent = field(
        default_factory=lambda: TopicRefineAgent(LLMConfig.load(settings.llm_config_path))
    )
    # Step2: Classifier Agent & Feature Agent（复用同一个 NLI 模型）
    classifier: ClassifierAgent = field(
        default_factory=lambda: ClassifierAgent(
            model_name=settings.classifier_model,
            candidate_labels=[l.strip() for l in settings.classifier_labels.split(",") if l.strip()],
        )
    )
    feature_agent: FeatureAgent = field(
        default_factory=lambda: FeatureAgent(model_name=settings.classifier_model)
    )
    # Step3: Memory Agent + GraphRAG Querier
    memory_store: RedisMemoryStore = field(
        default_factory=lambda: RedisMemoryStore(
            redis_url=settings.redis_url,
            window_days=settings.memory_window_days,
        )
    )
    memory_agent: MemoryAgent = field(default=None)  # 延迟初始化
    graphrag_querier: GraphRAGQuerier = field(default=None)  # 延迟初始化
    # Step4: ReportAgent
    report_agent: ReportAgent = field(
        default_factory=lambda: ReportAgent(
            weight_stock=settings.report_weight_stock,
            weight_sentiment=settings.report_weight_sentiment,
            weight_policy=settings.report_weight_policy,
            weight_spread=settings.report_weight_spread,
        )
    )
    graph_client: Neo4jGraphClient = field(
        default_factory=lambda: Neo4jGraphClient(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
        )
    )
    checkpoint: CheckpointStore = field(
        default_factory=lambda: CheckpointStore(settings.checkpoint_file)
    )
    seed_injector: RealtimeSeedInjector = field(default_factory=RealtimeSeedInjector)
    sources_config: SourcesConfig = field(
        default_factory=lambda: SourcesConfig.load(settings.sources_config_path)
    )


runtime = PipelineRuntime()
# Step3: 延迟初始化依赖 runtime 自身的组件
runtime.memory_agent = MemoryAgent(runtime.memory_store)
runtime.graphrag_querier = GraphRAGQuerier(runtime.graph_client)


def init_graph_schema() -> bool:
    """延迟初始化图谱 schema，避免模块导入阶段因 Neo4j 未启动直接崩溃。"""
    try:
        runtime.graph_client.ensure_schema()
        return True
    except ServiceUnavailable:
        return False
    except Neo4jError:
        return False


def fetch_news_node(state: PipelineState) -> PipelineState:
    last_dt = runtime.checkpoint.load_last_published_at()

    # 从所有 newsnow 端点抓取
    news_batch: list[NewsItem] = []
    for endpoint in runtime.sources_config.newsnow:
        items = fetch_newsnow(
            api_url=endpoint.url,
            sources=endpoint.sources,
            limit=settings.batch_size,
            since=last_dt,
        )
        news_batch.extend(items)

    seed_batch = runtime.seed_injector.load()

    batch = deduplicate_news(news_batch + seed_batch)
    if last_dt:
        batch = [b for b in batch if b.published_at > last_dt]

    # 排除数据库中已有分析结果的新闻（以 URL 为唯一标识）
    if batch:
        from opennews.db import get_existing_urls
        try:
            existing = get_existing_urls([b.url for b in batch])
            if existing:
                before = len(batch)
                batch = [b for b in batch if b.url not in existing]
                logger.info("dedup: %d already in DB, %d new", before - len(batch), len(batch))
        except Exception:
            logger.exception("dedup check failed, proceeding with full batch")

    batch.sort(key=lambda x: x.published_at)
    return {"news_batch": batch}


def embed_node(state: PipelineState) -> PipelineState:
    news = state.get("news_batch", [])
    if not news:
        return {"docs": [], "embeddings": []}

    docs = [f"{n.title}\n{n.content}" for n in news]
    vecs = runtime.embedder.encode(docs).vectors
    return {"docs": docs, "embeddings": vecs.tolist()}


def entity_node(state: PipelineState) -> PipelineState:
    docs = state.get("docs", [])
    if not docs:
        return {"entities": []}
    entities = [runtime.extractor.extract(d) for d in docs]
    return {"entities": entities}


def topic_node(state: PipelineState) -> PipelineState:
    docs = state.get("docs", [])
    embeddings = state.get("embeddings", [])
    if not docs:
        return {"topics": []}
    topics = runtime.topic_model.update_and_assign(docs, embeddings=embeddings or None)
    return {"topics": topics}


def refine_topics_node(state: PipelineState) -> PipelineState:
    """LLM 主题精炼：对聚类候选组进行语义拆分。"""
    docs = state.get("docs", [])
    topics = state.get("topics", [])
    if not docs or not topics:
        return {"topics": topics}

    labels = {a.topic_id: runtime.topic_model.get_topic_label(a.topic_id) for a in topics}
    refined, refined_labels = runtime.topic_refine_agent.refine_topics(docs, topics, labels)

    # 回写 labels 到 topic_model 以便后续 get_topic_label 正常工作
    runtime.topic_model._labels.update(refined_labels)

    return {"topics": refined}


# ── Step2: Classifier Agent 节点 ──────────────────────────────
def classify_node(state: PipelineState) -> PipelineState:
    """零样本分类：金融/政策/公司事件等。"""
    docs = state.get("docs", [])
    if not docs:
        return {"classifications": []}
    try:
        classifications = runtime.classifier.classify_batch(docs)
    except Exception:
        logger.exception("classify_node failed, fallback to empty")
        from opennews.agents.classifier_agent import ClassificationResult
        classifications = [
            ClassificationResult(category="unknown", confidence=0.0, all_scores={})
            for _ in docs
        ]
    return {"classifications": classifications}


# ── Step2: Feature Agent 节点 ─────────────────────────────────
def feature_node(state: PipelineState) -> PipelineState:
    """7 维新闻价值特征提取 + 影响分。"""
    docs = state.get("docs", [])
    if not docs:
        return {"features": []}
    try:
        features = runtime.feature_agent.extract_features_batch(docs)
    except Exception:
        logger.exception("feature_node failed, fallback to defaults")
        from opennews.agents.feature_agent import FeatureVector
        features = [FeatureVector() for _ in docs]
    return {"features": features}


def build_payload_node(state: PipelineState) -> PipelineState:
    news = state.get("news_batch", [])
    embeds = state.get("embeddings", [])
    entities = state.get("entities", [])
    topics = state.get("topics", [])
    classifications = state.get("classifications", [])
    features = state.get("features", [])

    if not news:
        return {"payloads": []}

    payloads = []
    safe_n = min(len(news), len(embeds), len(entities), len(topics))
    for i in range(safe_n):
        item = news[i]
        topic = topics[i]
        label = runtime.topic_model.get_topic_label(topic.topic_id)
        payload = build_graph_payload(
            item=item,
            embedding=embeds[i],
            entities=entities[i],
            topic=topic,
            topic_label=label,
        )
        # Step2: 注入分类 & 特征到 payload
        clf_dict = None
        feat_dict = None
        if i < len(classifications):
            clf = classifications[i]
            clf_dict = {
                "category": clf.category,
                "confidence": clf.confidence,
                "all_scores": clf.all_scores,
            }
        if i < len(features):
            feat = features[i]
            feat_dict = feat.to_dict()

        payloads.append(GraphPayload(
            news=payload["news"],
            entities=payload["entities"],
            topic=payload["topic"],
            impacts=payload["impacts"],
            classification=clf_dict,
            features=feat_dict,
        ))

    return {"payloads": payloads}


def dump_output_node(state: PipelineState) -> PipelineState:
    """每轮把解析结果（含 report）写入 PostgreSQL。"""
    payloads = state.get("payloads", [])
    reports = state.get("reports", [])
    if not payloads:
        return {}

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"

    records = []
    for p in payloads:
        news = p.news.copy()
        # embedding 只保留前 8 维，避免数据过大
        emb = news.get("embedding", [])
        news["embedding_preview"] = emb[:8]
        news.pop("embedding", None)

        records.append({
            "news": news,
            "entities": p.entities,
            "topic": p.topic,
            "impacts": p.impacts,
            "classification": p.classification,
            "features": p.features,
            "report": p.report if p.report else None,
        })

    try:
        ensure_pg_schema()
        batch_id = insert_batch(ts, records)
        logger.info("dumped %d records to PostgreSQL (batch_id=%d, ts=%s)", len(records), batch_id, ts)

        # 写入 reports 表
        if reports:
            reports_data = [
                {
                    "news_id": r.news_id,
                    "final_score": r.final_score,
                    "impact_level": r.impact_level,
                    "dk_cot_scores": r.dk_cot_scores.to_dict(),
                    "markdown": r.markdown,
                    "viz_suggestions": r.viz_suggestions,
                }
                for r in reports
            ]
            insert_reports(batch_id, reports_data)
    except Exception:
        logger.exception("failed to dump batch to PostgreSQL")

    return {}


def write_graph_node(state: PipelineState) -> PipelineState:
    payloads = state.get("payloads", [])
    news_batch = state.get("news_batch", [])

    if not payloads:
        return {"result": "updated 0 news into graph"}

    if not init_graph_schema():
        return {"result": "neo4j unavailable, skip graph write this round"}

    try:
        runtime.graph_client.upsert_batch(payloads)
    except ServiceUnavailable:
        return {"result": "neo4j unavailable, skip graph write this round"}

    latest = max(n.published_at for n in news_batch)
    runtime.checkpoint.save_last_published_at(latest)
    return {"result": f"updated {len(payloads)} news into graph"}


# ── Step3: Memory Agent 节点 ──────────────────────────────────
def memory_ingest_node(state: PipelineState) -> PipelineState:
    """将当前批次写入时序记忆（Redis / fallback）。"""
    payloads = state.get("payloads", [])
    if not payloads:
        return {"topic_trends": {}}

    records: list[MemoryRecord] = []
    for p in payloads:
        records.append(MemoryRecord(
            news_id=p.news.get("news_id", ""),
            topic_id=p.topic.get("topic_id", -1),
            published_at=p.news.get("published_at", ""),
            category=(p.classification or {}).get("category", "unknown"),
            impact_score=(p.features or {}).get("impact_score", 0.0),
            features=p.features or {},
        ))

    try:
        runtime.memory_agent.ingest(records)
    except Exception:
        logger.exception("memory ingest failed")

    # 聚合当前批次涉及的所有 topic
    topic_ids = {r.topic_id for r in records}
    try:
        trends = runtime.memory_agent.aggregate_batch_topics(
            topic_ids, window_days=settings.memory_window_days
        )
    except Exception:
        logger.exception("memory aggregation failed")
        trends = {}

    return {"topic_trends": trends}


# ── Step3: 趋势写入 GraphRAG 节点 ─────────────────────────────
def update_trends_node(state: PipelineState) -> PipelineState:
    """将累积影响趋势写入 Neo4j Topic 节点。"""
    trends = state.get("topic_trends", {})
    if not trends:
        return {}

    updated = 0
    for topic_id, trend in trends.items():
        trend_data = {
            "trend_direction": trend.trend_direction,
            "avg_impact": trend.avg_impact,
            "latest_impact": trend.latest_impact,
            "total_news_count": trend.total_news_count,
        }
        try:
            if runtime.graphrag_querier.upsert_topic_trend(topic_id, trend_data):
                updated += 1
        except Exception:
            logger.exception("trend upsert failed for topic %d", topic_id)

    logger.info("updated trends for %d/%d topics", updated, len(trends))
    return {}


# ── Step4: ReportAgent 节点 ───────────────────────────────────
def report_node(state: PipelineState) -> PipelineState:
    """DK-CoT 多维度评分 + Markdown 报告生成。可通过 REPORT_ENABLED 开关。"""
    if not settings.report_enabled:
        logger.info("report generation disabled, skipping")
        return {"reports": []}

    payloads = state.get("payloads", [])
    trends = state.get("topic_trends", {})
    if not payloads:
        return {"reports": []}

    # 构建 ReportAgent 所需的输入格式
    eval_items = []
    for p in payloads:
        eval_items.append({
            "news": p.news,
            "features": p.features or {},
            "classification": p.classification or {},
            "entities": p.entities,
            "topic": p.topic,
        })

    try:
        reports = runtime.report_agent.evaluate_batch(eval_items, trends=trends)
    except Exception:
        logger.exception("report_node failed")
        reports = []

    # 将 report 数据回写到 payloads（用于后续持久化）
    for i, report in enumerate(reports):
        if i < len(payloads):
            payloads[i] = GraphPayload(
                news=payloads[i].news,
                entities=payloads[i].entities,
                topic=payloads[i].topic,
                impacts=payloads[i].impacts,
                classification=payloads[i].classification,
                features=payloads[i].features,
                report=report.to_dict(),
            )

    return {"reports": reports, "payloads": payloads}


def build_pipeline():
    g = StateGraph(PipelineState)
    g.add_node("fetch_news", fetch_news_node)
    g.add_node("embed", embed_node)
    g.add_node("extract_entities", entity_node)
    g.add_node("topics", topic_node)
    g.add_node("refine_topics", refine_topics_node)
    # Step2: Agent 节点
    g.add_node("classify", classify_node)
    g.add_node("extract_features", feature_node)
    g.add_node("build_payload", build_payload_node)
    g.add_node("dump_output", dump_output_node)
    # Step3: 时序记忆 & 趋势
    g.add_node("memory_ingest", memory_ingest_node)
    g.add_node("update_trends", update_trends_node)
    # Step4: 报告生成 + 图谱写入
    g.add_node("report", report_node)
    g.add_node("write_graph", write_graph_node)

    g.set_entry_point("fetch_news")
    g.add_edge("fetch_news", "embed")
    g.add_edge("embed", "extract_entities")
    # 并行分支：entities → topics / classify / features
    g.add_edge("extract_entities", "topics")
    g.add_edge("extract_entities", "classify")
    g.add_edge("extract_entities", "extract_features")
    # topics → LLM refine → build_payload
    g.add_edge("topics", "refine_topics")
    g.add_edge("refine_topics", "build_payload")
    g.add_edge("classify", "build_payload")
    g.add_edge("extract_features", "build_payload")
    g.add_edge("build_payload", "memory_ingest")
    # Step3: 时序记忆聚合
    g.add_edge("memory_ingest", "update_trends")
    # Step4: report 需要 trends → dump_output 在 report 之后写入 PG（含完整 report）
    g.add_edge("update_trends", "report")
    g.add_edge("report", "dump_output")
    g.add_edge("dump_output", "write_graph")
    g.add_edge("write_graph", END)
    return g.compile()


def run_once() -> str:
    app = build_pipeline()
    out = app.invoke({})
    return out.get("result", "done")
