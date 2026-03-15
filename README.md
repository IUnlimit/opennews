<div align="center">

# OpenNews

Real-time financial news knowledge graph & impact assessment system

实时金融新闻知识图谱与影响评估系统

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

**English** | [中文](#中文文档)

## Overview

OpenNews is a LangGraph-orchestrated pipeline that ingests multi-platform financial news, performs NLP analysis (NER, topic clustering, zero-shot classification, 7-dimension feature extraction), maintains temporal memory, computes DK-CoT impact scores (0–100), and persists everything into a Neo4j knowledge graph and PostgreSQL database. A built-in web dashboard lets you browse, filter, and inspect results in real time.

### Pipeline DAG

```
fetch_news → embed → extract_entities ─┬→ topics ──────────┐
                                       ├→ classify ────────┤
                                       └→ extract_features ┘
                                               ↓
                                         build_payload → dump_output
                                               ↓
                                         memory_ingest → update_trends
                                               ↓
                                            report → write_graph → END
```

After `extract_entities`, three branches run in parallel (BERTopic clustering / DeBERTa zero-shot classification / 7-dim feature extraction), then converge into temporal memory aggregation, DK-CoT impact scoring, and graph persistence.

### Key Features

- Multi-source ingestion — NewsNow API, RSS, JSONL seed files
- FinBERT embeddings (768-dim) + hierarchical cosine-threshold clustering
- DeBERTa-v3 zero-shot classification (financial / policy / company / macro / industry)
- 7-dimension news-value scoring (market impact, price signal, regulatory risk, timeliness, impact, controversy, generalizability)
- Redis-backed 30-day rolling temporal memory with daily sentiment aggregation
- DK-CoT 4-dimension impact scoring: stock relevance (40%), market sentiment (20%), policy risk (20%), spread breadth (20%)
- LLM-powered topic refinement with bilingual (zh/en) labels
- Neo4j knowledge graph (News / Entity / Topic nodes + MENTIONS / IN_TOPIC / IMPACTS relations)
- PostgreSQL batch persistence with URL-based deduplication
- Real-time web dashboard with score distribution chart, dual-range slider, and detail panel

## Requirements

| Service | Purpose | Required | Default Address |
|---------|---------|----------|-----------------|
| PostgreSQL 16+ | Primary storage | Yes | `127.0.0.1:5432` |
| Neo4j 5+ | Knowledge graph | No (skipped if unavailable) | `bolt://127.0.0.1:7687` |
| Redis 7+ | Temporal memory | No (falls back to in-memory) | `127.0.0.1:6379` |

### Quick Start with Docker

```bash
# Start all services
docker compose -f docker/docker-compose.yml up -d

# Verify
docker compose -f docker/docker-compose.yml ps
```

This brings up PostgreSQL, Neo4j, and Redis with health checks and resource limits. See `docker/docker-compose.yml` for full configuration.

## Installation

```bash
git clone https://github.com/user/opennews.git && cd opennews

python3.10 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

The following HuggingFace models are downloaded automatically on first run (~1.5 GB total):

| Model | Purpose | Size |
|-------|---------|------|
| `ProsusAI/finbert` | Financial text embedding + BERTopic | ~440 MB |
| `dslim/bert-base-NER` | Named entity recognition | ~430 MB |
| `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | Zero-shot classification + feature extraction | ~440 MB |

## Usage

### Run the Pipeline

```bash
# Start the polling scheduler (runs every 5 minutes)
PYTHONPATH=src python -m opennews.main
```

### Run the Web Dashboard

```bash
# In a separate terminal
PYTHONPATH=src python web/server.py --port 8080
```

Open http://localhost:8080 to browse results.

### One-Command Start

```bash
# build.sh starts all services, checks dependencies, and launches both backend + frontend
./build.sh
```

### Clean All Data

```bash
./db-clean.sh
```

## Configuration

All settings can be overridden via environment variables.

| Variable | Description | Default |
|----------|-------------|---------|
| `NEWS_POLL_INTERVAL_MIN` | Polling interval (minutes) | `5` |
| `BATCH_SIZE` | Max items per fetch | `32` |
| `EMBEDDING_MODEL` | Embedding model | `ProsusAI/finbert` |
| `NER_MODEL` | NER model | `dslim/bert-base-NER` |
| `NEO4J_URI` | Neo4j connection | `bolt://127.0.0.1:7687` |
| `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j credentials | `neo4j` / `Aa123456` |
| `CLASSIFIER_MODEL` | Zero-shot model | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` |
| `REDIS_URL` | Redis connection | `redis://127.0.0.1:6379/0` |
| `MEMORY_WINDOW_DAYS` | Temporal memory window | `30` |
| `PG_HOST` / `PG_PORT` / `PG_USER` / `PG_PASSWORD` / `PG_DATABASE` | PostgreSQL | `127.0.0.1` / `5432` / `postgres` / `123456` / `opennews` |
| `REPORT_ENABLED` | Enable impact reports | `true` |
| `REPORT_WEIGHT_STOCK` | Stock relevance weight | `0.40` |
| `REPORT_WEIGHT_SENTIMENT` | Market sentiment weight | `0.20` |
| `REPORT_WEIGHT_POLICY` | Policy risk weight | `0.20` |
| `REPORT_WEIGHT_SPREAD` | Spread breadth weight | `0.20` |
| `LLM_API_KEY` | LLM API key for topic refinement | — |
| `LLM_BASE_URL` | LLM endpoint (OpenAI-compatible) | — |
| `LLM_MODEL` | LLM model name | `gpt-4o-mini` |

Additional config files:
- `config/sources.yaml` — News source endpoints and channels
- `config/llm.yaml` — LLM provider settings and topic refinement prompts

## News Input

### NewsNow API (default)

Configure endpoints in `config/sources.yaml`:

```yaml
newsnow:
  - url: https://newsnow.busiyi.world/api/s/entire
    sources:
      - wallstreetcn-news
      - cls-telegraph
      - 36kr-quick
```

### Seed File (manual / batch)

Write news items to `seeds/realtime_seeds.jsonl`, one JSON object per line:

```jsonl
{"news_id":"seed-001","title":"Fed hints at slower rate cuts","content":"Officials signal a cautious approach.","source":"seed","url":"seed://seed-001","published_at":"2026-03-09T07:30:00+00:00"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `news_id` | string | Yes | Unique identifier |
| `title` | string | Yes | Headline |
| `content` | string | No | Body text (defaults to title) |
| `source` | string | No | Source tag (default `"seed"`) |
| `url` | string | No | Original URL |
| `published_at` | string | No | ISO 8601 timestamp (default: now) |

## Output

### PostgreSQL (primary)

Query via the web API or directly:

```sql
-- Recent high-impact news
SELECT payload->>'news'->>'title', payload->'report'->>'final_score'
FROM batch_records br JOIN batches b ON br.batch_id = b.batch_id
WHERE (payload->'report'->>'impact_level') = '高'
ORDER BY b.created_at DESC;
```

### Web API

| Endpoint | Description |
|----------|-------------|
| `GET /api/batches` | List all batches |
| `GET /api/batches/latest` | Latest batch records |
| `GET /api/batches/<id>` | Records by batch ID |
| `GET /api/records?hours=N` | Records from last N hours |

### Neo4j Knowledge Graph

Access via Neo4j Browser at http://localhost:7474.

```cypher
-- High-impact news
MATCH (n:News) WHERE n.impact_level = '高'
RETURN n.title, n.final_impact_score ORDER BY n.final_impact_score DESC

-- Topic trends
MATCH (t:Topic) WHERE t.trend_direction IS NOT NULL
RETURN t.label, t.trend_direction, t.avg_impact ORDER BY t.avg_impact DESC

-- Entity network
MATCH (e1:Entity)-[r:IMPACTS]->(e2:Entity)
RETURN e1.name, e2.name, r.weight ORDER BY r.weight DESC LIMIT 20
```

## Project Structure

```
opennews/
├── src/opennews/
│   ├── main.py                        # Entry point
│   ├── config.py                      # Global settings
│   ├── db.py                          # PostgreSQL persistence
│   ├── agents/
│   │   ├── classifier_agent.py        # DeBERTa zero-shot classification
│   │   ├── feature_agent.py           # 7-dim feature extraction
│   │   ├── memory_agent.py            # Temporal aggregation
│   │   ├── report_agent.py            # DK-CoT impact scoring
│   │   └── topic_refine_agent.py      # LLM topic refinement
│   ├── graph/
│   │   ├── neo4j_client.py            # Neo4j connection & upsert
│   │   ├── upsert.py                  # GraphPayload builder
│   │   └── subgraph_query.py          # Subgraph query & community detection
│   ├── ingest/
│   │   ├── news_fetcher.py            # Multi-platform parallel fetch
│   │   ├── sources.py                 # Source config loader
│   │   ├── checkpoint.py              # Incremental checkpoint
│   │   └── seed_injector.py           # JSONL seed injection
│   ├── llm/
│   │   └── client.py                  # OpenAI-compatible LLM client
│   ├── memory/
│   │   └── __init__.py                # Redis temporal store
│   ├── nlp/
│   │   ├── embedder.py                # FinBERT embedding
│   │   └── entity_extractor.py        # NER extraction
│   ├── topic/
│   │   └── online_topic_model.py      # Hierarchical cosine clustering
│   ├── scheduler/
│   │   └── polling_job.py             # APScheduler polling
│   └── workflow/
│       └── langgraph_pipeline.py      # LangGraph DAG
├── web/
│   ├── server.py                      # Web server (API + static)
│   ├── index.html / style.css / app.js
├── config/
│   ├── llm.yaml                       # LLM settings
│   └── sources.yaml                   # News source config
├── docker/
│   └── docker-compose.yml             # PostgreSQL + Neo4j + Redis
├── seeds/
│   └── realtime_seeds.jsonl           # Seed news
├── build.sh                           # One-command launcher
├── db-clean.sh                        # Data cleanup script
└── requirements.txt
```

## License

MIT

---

<a id="中文文档"></a>

## 中文文档

[English](#overview) | **中文**

## 概述

OpenNews 是一个基于 LangGraph 编排的金融新闻处理流水线。自动抓取多平台新闻，完成 NER 实体抽取、主题聚类、零样本分类、7 维特征提取、时序记忆聚合、DK-CoT 影响评分，并将结果写入 Neo4j 知识图谱和 PostgreSQL 数据库。内置 Web 面板支持实时浏览、筛选和查看详情。

### 流水线 DAG

```
抓取新闻 → 嵌入 → 实体抽取 ─┬→ 主题聚类 ──────┐
                            ├→ 零样本分类 ────┤
                            └→ 特征提取 ──────┘
                                    ↓
                              构建载荷 → 输出文件
                                    ↓
                              记忆写入 → 趋势更新
                                    ↓
                                报告生成 → 图谱写入 → END
```

### 核心能力

- 多源抓取 — NewsNow API、RSS、JSONL 种子文件
- FinBERT 嵌入 (768 维) + 层次余弦阈值聚类
- DeBERTa-v3 零样本分类（金融市场 / 政策法规 / 公司事件 / 宏观经济 / 行业趋势）
- 7 维新闻价值评分（市场影响、价格信号、监管风险、时效性、影响力、争议性、可推广性）
- Redis 30 天滚动时序记忆 + 每日情绪聚合
- DK-CoT 四维影响评分：股价相关性 (40%)、市场情绪 (20%)、政策风险 (20%)、传播广度 (20%)
- LLM 主题精炼 + 中英双语标签
- Neo4j 知识图谱（News / Entity / Topic 节点 + MENTIONS / IN_TOPIC / IMPACTS 关系）
- PostgreSQL 批次持久化 + URL 去重
- 实时 Web 面板：分数分布图、双端滑块筛选、详情侧边栏

## 依赖服务

| 服务 | 用途 | 必需 | 默认地址 |
|------|------|------|----------|
| PostgreSQL 16+ | 主存储 | 是 | `127.0.0.1:5432` |
| Neo4j 5+ | 知识图谱 | 否（不可用时跳过） | `bolt://127.0.0.1:7687` |
| Redis 7+ | 时序记忆 | 否（不可用时回退到内存） | `127.0.0.1:6379` |

### Docker 快速启动

```bash
# 启动所有服务
docker compose -f docker/docker-compose.yml up -d

# 验证状态
docker compose -f docker/docker-compose.yml ps
```

## 安装

```bash
git clone https://github.com/user/opennews.git && cd opennews

python3.10 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

首次运行时自动下载以下 HuggingFace 模型（共约 1.5 GB）：

| 模型 | 用途 | 大小 |
|------|------|------|
| `ProsusAI/finbert` | 金融文本嵌入 + BERTopic | ~440 MB |
| `dslim/bert-base-NER` | 命名实体识别 | ~430 MB |
| `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | 零样本分类 + 特征提取 | ~440 MB |

## 使用

### 启动流水线

```bash
# 启动定时轮询（每 5 分钟一次）
PYTHONPATH=src python -m opennews.main
```

### 启动 Web 面板

```bash
# 另开终端
PYTHONPATH=src python web/server.py --port 8080
```

浏览器打开 http://localhost:8080 查看结果。

### 一键启动

```bash
./build.sh
```

### 清除数据

```bash
./db-clean.sh
```

## 配置

所有配置均可通过环境变量覆盖，完整列表见[英文配置表](#configuration)。

额外配置文件：
- `config/sources.yaml` — 新闻源端点和频道
- `config/llm.yaml` — LLM 提供商设置和主题精炼提示词

## 新闻输入

### NewsNow API（默认）

在 `config/sources.yaml` 中配置端点：

```yaml
newsnow:
  - url: https://newsnow.busiyi.world/api/s/entire
    sources:
      - wallstreetcn-news
      - cls-telegraph
      - 36kr-quick
```

### 种子文件（手动 / 批量）

将新闻写入 `seeds/realtime_seeds.jsonl`，每行一个 JSON 对象：

```jsonl
{"news_id":"seed-001","title":"美联储暗示放缓降息","content":"官员们在通胀粘性背景下发出谨慎信号。","source":"seed","url":"seed://seed-001","published_at":"2026-03-09T07:30:00+00:00"}
```

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `news_id` | string | 是 | 唯一标识 |
| `title` | string | 是 | 新闻标题 |
| `content` | string | 否 | 正文（缺省使用标题） |
| `source` | string | 否 | 来源标识（默认 `"seed"`） |
| `url` | string | 否 | 原文链接 |
| `published_at` | string | 否 | ISO 8601 时间戳（默认当前时间） |

## 输出数据

### PostgreSQL（主存储）

通过 Web API 或直接 SQL 查询：

```sql
-- 最近的高影响新闻
SELECT payload->>'news'->>'title', payload->'report'->>'final_score'
FROM batch_records br JOIN batches b ON br.batch_id = b.batch_id
WHERE (payload->'report'->>'impact_level') = '高'
ORDER BY b.created_at DESC;
```

### Web API

| 端点 | 说明 |
|------|------|
| `GET /api/batches` | 列出所有批次 |
| `GET /api/batches/latest` | 最新批次记录 |
| `GET /api/batches/<id>` | 指定批次记录 |
| `GET /api/records?hours=N` | 最近 N 小时的记录 |

### Neo4j 知识图谱

通过 Neo4j Browser (http://localhost:7474) 查询：

```cypher
-- 高影响新闻
MATCH (n:News) WHERE n.impact_level = '高'
RETURN n.title, n.final_impact_score ORDER BY n.final_impact_score DESC

-- 主题趋势
MATCH (t:Topic) WHERE t.trend_direction IS NOT NULL
RETURN t.label, t.trend_direction, t.avg_impact ORDER BY t.avg_impact DESC

-- 实体关系网络
MATCH (e1:Entity)-[r:IMPACTS]->(e2:Entity)
RETURN e1.name, e2.name, r.weight ORDER BY r.weight DESC LIMIT 20
```

## 许可证

MIT
