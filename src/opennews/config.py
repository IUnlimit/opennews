from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    poll_interval_minutes: int = int(os.getenv("NEWS_POLL_INTERVAL_MIN", "5"))
    batch_size: int = int(os.getenv("BATCH_SIZE", "32"))
    # 推荐金融模型：ProsusAI/finbert（768维）或你自己的 FinRoBERTa/DeBERTa checkpoint
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "ProsusAI/finbert")
    ner_model: str = os.getenv("NER_MODEL", "dslim/bert-base-NER")

    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "Aa123456")

    # Step2: 分类 & 特征提取
    classifier_model: str = os.getenv("CLASSIFIER_MODEL", "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")
    classifier_labels: str = os.getenv(
        "CLASSIFIER_LABELS",
        "financial_market,policy_regulation,company_event,macro_economy,industry_trend",
    )

    # Step3: Redis 时序记忆
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    memory_window_days: int = int(os.getenv("MEMORY_WINDOW_DAYS", "30"))

    # Step4: ReportAgent 配置
    report_enabled: bool = os.getenv("REPORT_ENABLED", "true").lower() in ("true", "1", "yes")
    # DK-CoT 四维权重：股价相关性 / 市场情绪 / 政策风险 / 传播广度
    report_weight_stock: float = float(os.getenv("REPORT_WEIGHT_STOCK", "0.40"))
    report_weight_sentiment: float = float(os.getenv("REPORT_WEIGHT_SENTIMENT", "0.20"))
    report_weight_policy: float = float(os.getenv("REPORT_WEIGHT_POLICY", "0.20"))
    report_weight_spread: float = float(os.getenv("REPORT_WEIGHT_SPREAD", "0.20"))

    # PostgreSQL 持久化
    pg_host: str = os.getenv("PG_HOST", "127.0.0.1")
    pg_port: int = int(os.getenv("PG_PORT", "5432"))
    pg_user: str = os.getenv("PG_USER", "postgres")
    pg_password: str = os.getenv("PG_PASSWORD", "123456")
    pg_database: str = os.getenv("PG_DATABASE", "opennews")

    checkpoint_file: str = os.getenv("CHECKPOINT_FILE", "seeds/checkpoint.json")

    # 配置文件路径
    llm_config_path: str = os.getenv("LLM_CONFIG_PATH", "config/llm.yaml")
    sources_config_path: str = os.getenv("SOURCES_CONFIG_PATH", "config/sources.yaml")

    # 分享图片功能
    share_api_enabled: bool = os.getenv("SHARE_API_ENABLED", "true").lower() in ("true", "1", "yes")
    share_scheduler_enabled: bool = os.getenv("SHARE_SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes")
    share_refresh_minutes: int = int(os.getenv("SHARE_REFRESH_MINUTES", "30"))
    share_default_hours: float = float(os.getenv("SHARE_DEFAULT_HOURS", "24"))
    share_default_score_lo: float = float(os.getenv("SHARE_DEFAULT_SCORE_LO", "50"))
    share_default_score_hi: float = float(os.getenv("SHARE_DEFAULT_SCORE_HI", "100"))
    share_default_lang: str = os.getenv("SHARE_DEFAULT_LANG", "zh")
    share_default_limit: int = int(os.getenv("SHARE_DEFAULT_LIMIT", "5"))
    share_cache_path: str = os.getenv("SHARE_CACHE_PATH", "data/share/default-share.svg")


settings = Settings()
