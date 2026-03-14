from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from opennews.config import settings
from opennews.db import ensure_schema as ensure_pg_schema
from opennews.ingest.sources import SourcesConfig
from opennews.workflow.langgraph_pipeline import run_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("opennews.scheduler")


def job() -> None:
    try:
        result = run_once()
        logger.info("pipeline success: %s", result)
    except Exception as e:
        logger.exception("pipeline failed: %s", e)


def start_scheduler() -> None:
    # 启动时确保配置文件存在（不存在则自动创建默认）
    SourcesConfig.load(settings.sources_config_path)

    # 启动时立即建表，确保 PG schema 就绪（不依赖 pipeline 是否有数据）
    try:
        ensure_pg_schema()
    except Exception:
        logger.exception("failed to ensure PG schema on startup")

    scheduler = BlockingScheduler()
    scheduler.add_job(job, "interval", minutes=settings.poll_interval_minutes)
    logger.info("scheduler started, interval=%s min", settings.poll_interval_minutes)
    job()  # 启动时先跑一轮
    scheduler.start()
