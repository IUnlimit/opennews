"""PostgreSQL 持久化层 — 批次数据 & 报告存储。

表结构：
  batches       — 每轮流水线产出一行（batch_id, created_at, record_count）
  batch_records — 每条新闻的完整分析结果（JSON 存储，关联 batch_id）
  reports       — Markdown 报告 & 摘要（关联 batch_id）
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from opennews.config import settings

logger = logging.getLogger(__name__)

_pool: pool.SimpleConnectionPool | None = None


def _get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            host=settings.pg_host,
            port=settings.pg_port,
            user=settings.pg_user,
            password=settings.pg_password,
            database=settings.pg_database,
        )
    return _pool


@contextmanager
def get_conn():
    p = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


# ── 建表 ──────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id    SERIAL PRIMARY KEY,
    batch_ts    VARCHAR(20) NOT NULL UNIQUE,   -- YYYYMMDD_HHMMSS_mmm
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    record_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS batch_records (
    id          SERIAL PRIMARY KEY,
    batch_id    INTEGER NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    news_id     VARCHAR(128),
    payload     JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batch_records_batch ON batch_records(batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_records_news  ON batch_records(news_id);

CREATE TABLE IF NOT EXISTS reports (
    id          SERIAL PRIMARY KEY,
    batch_id    INTEGER NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
    news_id     VARCHAR(128),
    impact_level VARCHAR(4),
    markdown    TEXT,
    summary     JSONB
);
CREATE INDEX IF NOT EXISTS idx_reports_batch ON reports(batch_id);

-- migrations: 兼容已有表
ALTER TABLE batches ALTER COLUMN batch_ts TYPE VARCHAR(20);

DO $$ BEGIN
    ALTER TABLE batch_records ADD COLUMN news_url TEXT;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_records_url ON batch_records(news_url);
"""


def ensure_schema():
    """创建表（幂等）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
    logger.info("PostgreSQL schema ensured")


# ── 写入 ──────────────────────────────────────────────────

def get_existing_urls(urls: list[str]) -> set[str]:
    """查询数据库中已存在的新闻 URL 集合。"""
    if not urls:
        return set()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT news_url FROM batch_records WHERE news_url = ANY(%s)",
                (urls,),
            )
            return {row[0] for row in cur.fetchall()}


def insert_batch(batch_ts: str, records: list[dict]) -> int:
    """插入一个批次及其所有记录（跳过 URL 已存在的），返回 batch_id。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO batches (batch_ts, record_count) VALUES (%s, %s) RETURNING batch_id",
                (batch_ts, len(records)),
            )
            batch_id = cur.fetchone()[0]

            inserted = 0
            for rec in records:
                news = rec.get("news") or {}
                news_id = news.get("news_id")
                news_url = news.get("url")
                cur.execute(
                    "INSERT INTO batch_records (batch_id, news_id, news_url, payload) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (news_url) DO NOTHING",
                    (batch_id, news_id, news_url, json.dumps(rec, ensure_ascii=False)),
                )
                inserted += cur.rowcount

            # 更新实际插入数
            cur.execute(
                "UPDATE batches SET record_count = %s WHERE batch_id = %s",
                (inserted, batch_id),
            )
    logger.info("inserted batch %s (%d/%d records, %d skipped) → batch_id=%d",
                batch_ts, inserted, len(records), len(records) - inserted, batch_id)
    return batch_id


def insert_reports(batch_id: int, reports_data: list[dict]):
    """插入报告摘要。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in reports_data:
                cur.execute(
                    "INSERT INTO reports (batch_id, news_id, impact_level, markdown, summary) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        batch_id,
                        r.get("news_id"),
                        r.get("impact_level"),
                        r.get("markdown"),
                        json.dumps({
                            "news_id": r.get("news_id"),
                            "final_score": r.get("final_score"),
                            "impact_level": r.get("impact_level"),
                            "dk_cot_scores": r.get("dk_cot_scores"),
                            "viz_suggestions": r.get("viz_suggestions"),
                        }, ensure_ascii=False),
                    ),
                )
    logger.info("inserted %d reports for batch_id=%d", len(reports_data), batch_id)


# ── 查询（供 Web Server 使用） ────────────────────────────

def list_batches() -> list[dict]:
    """列出所有批次（按时间倒序）。"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT batch_id, batch_ts, created_at, record_count "
                "FROM batches ORDER BY batch_ts DESC"
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_batch_records(batch_id: int) -> list[dict]:
    """获取指定批次的所有记录。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM batch_records WHERE batch_id = %s ORDER BY id",
                (batch_id,),
            )
            records = [row[0] for row in cur.fetchall()]
    # 注入 batch_id 到 topic 中，使 topic_id 跨批次唯一
    for rec in records:
        topic = rec.get("topic")
        if topic and "batch_id" not in topic:
            topic["batch_id"] = batch_id
    return records


def get_latest_batch_records() -> list[dict]:
    """获取最新批次的所有记录。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT batch_id FROM batches ORDER BY batch_ts DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return []
            return get_batch_records(row[0])


def get_batch_id_by_ts(batch_ts: str) -> int | None:
    """根据时间戳查找 batch_id。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT batch_id FROM batches WHERE batch_ts = %s", (batch_ts,))
            row = cur.fetchone()
            return row[0] if row else None


def get_records_since(hours: float) -> list[dict]:
    """获取最近 N 小时内的记录（按 news_url 去重，保留最新）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ON (COALESCE(br.news_url, br.id::text)) "
                "br.batch_id, br.payload "
                "FROM batch_records br "
                "JOIN batches b ON br.batch_id = b.batch_id "
                "WHERE b.created_at >= now() - interval '%s hours' "
                "ORDER BY COALESCE(br.news_url, br.id::text), br.id DESC",
                (hours,),
            )
            records = []
            for row in cur.fetchall():
                bid, payload = row[0], row[1]
                topic = payload.get("topic")
                if topic and "batch_id" not in topic:
                    topic["batch_id"] = bid
                records.append(payload)
            return records


# ── 未翻译标签重试 ─────────────────────────────────────

def get_untranslated_topic_labels(limit: int = 100) -> list[tuple[int, dict]]:
    """查询带 [EN]/[ZH] 前缀的未翻译主题标签。

    Returns:
        [(record_id, {"zh": "...", "en": "..."}), ...]
    """
    sql = """
        SELECT id, payload->'topic'->'label' AS label
        FROM batch_records
        WHERE (payload->'topic'->'label'->>'zh') LIKE '[EN] %%'
           OR (payload->'topic'->'label'->>'en') LIKE '[ZH] %%'
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [(row[0], row[1]) for row in cur.fetchall()]


def update_topic_labels(updates: list[tuple[int, dict]]) -> int:
    """批量更新 batch_records 中的主题标签。

    Args:
        updates: [(record_id, {"zh": "...", "en": "..."}), ...]

    Returns:
        实际更新的行数
    """
    if not updates:
        return 0
    updated = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for record_id, new_label in updates:
                cur.execute(
                    "UPDATE batch_records "
                    "SET payload = jsonb_set(payload, '{topic,label}', %s::jsonb) "
                    "WHERE id = %s",
                    (json.dumps(new_label, ensure_ascii=False), record_id),
                )
                updated += cur.rowcount
    logger.info("updated %d/%d topic labels in DB", updated, len(updates))
    return updated
