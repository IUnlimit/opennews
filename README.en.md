<div align="center">

# OpenNews

Real-time financial news knowledge graph & impact assessment system

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![中文](https://img.shields.io/badge/lang-中文-red.svg)](README.md)

</div>

---

## Overview

OpenNews is a LangGraph-orchestrated pipeline that ingests multi-platform financial news, performs NLP analysis (NER, topic clustering, zero-shot classification, 7-dimension feature extraction), maintains temporal memory, computes DK-CoT impact scores (0-100), and persists everything into a Neo4j knowledge graph and PostgreSQL database. A built-in web dashboard lets you browse, filter, and inspect results in real time.

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
| PostgreSQL 16+ | Primary storage | Yes | Internal only (container network) |
| Neo4j 5+ | Knowledge graph | No (skipped if unavailable) | Internal only (container network) |
| Redis 7+ | Temporal memory | No (falls back to in-memory) | Internal only (container network) |

Only the web dashboard port (default `8080`) is exposed to the host. All infrastructure services communicate through the Docker internal network.

### Quick Start with Docker

The backend container loads NLP models from the host's HuggingFace cache (`~/.cache/huggingface`) in offline mode. Download models on the host first if you haven't already:

```bash
# Download models on the host (one-time, ~1.5 GB)
pip install sentence-transformers transformers
python -c "
from sentence_transformers import SentenceTransformer
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
SentenceTransformer('ProsusAI/finbert')
pipeline('ner', model='dslim/bert-base-NER')
AutoTokenizer.from_pretrained('MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli')
AutoModelForSequenceClassification.from_pretrained('MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli')
"

# Start everything
docker compose -f docker/docker-compose.yml up -d

# Verify
docker compose -f docker/docker-compose.yml ps
```

If your HuggingFace cache is in a non-default location, set `HF_HOME`:

```bash
HF_HOME=/path/to/your/cache docker compose -f docker/docker-compose.yml up -d
```

This brings up PostgreSQL, Neo4j, Redis, the backend pipeline, and the web dashboard. All data is persisted to local directories under `docker/` (postgres, neo4j, redis). The `seeds/` and `config/` directories are mounted into the backend container, so you can edit news sources and seed files on the host and they take effect immediately.

Data volumes:

| Service | Host Path | Container Path |
|---------|-----------|----------------|
| PostgreSQL | `docker/postgres/` | `/var/lib/postgresql/data` |
| Neo4j | `docker/neo4j/data/`, `docker/neo4j/logs/` | `/data`, `/logs` |
| Redis | `docker/redis/` | `/data` |
| Backend config | `config/` | `/app/config` |
| Backend seeds | `seeds/` | `/app/seeds` |

Web dashboard: http://localhost:8080 (configurable via `WEB_PORT`)

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

### Docker (recommended)

```bash
# Start all services including backend pipeline and web dashboard
docker compose -f docker/docker-compose.yml up -d

# View logs
docker compose -f docker/docker-compose.yml logs -f backend

# Stop
docker compose -f docker/docker-compose.yml down
```

### Local Development

When developing locally outside Docker, you need the infra ports exposed on the host:

```bash
# Start infra with host-exposed ports
docker run -d --name opennews-pg -p 5432:5432 -e POSTGRES_PASSWORD=123456 -e POSTGRES_DB=opennews postgres:16-alpine
docker run -d --name opennews-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/Aa123456 neo4j:5-community
docker run -d --name opennews-redis -p 6379:6379 redis:7-alpine

# Run the pipeline
PYTHONPATH=src python -m opennews.main

# Run the web dashboard (separate terminal)
PYTHONPATH=src python web/server.py --port 8080
```

Open http://localhost:8080 to browse results.

### One-Command Start (legacy)

```bash
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
| `NEO4J_URI` | Neo4j connection | `bolt://neo4j:7687` (Docker) / `bolt://127.0.0.1:7687` (local) |
| `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j credentials | `neo4j` / `Aa123456` |
| `CLASSIFIER_MODEL` | Zero-shot model | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` (Docker) / `redis://127.0.0.1:6379/0` (local) |
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

Access via Neo4j Browser (requires local development setup with port `7474` exposed, see [Local Development](#local-development)).

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
│   └── docker-compose.yml             # Full stack: PG + Neo4j + Redis + backend + web
├── Dockerfile                         # Backend & web image
├── seeds/
│   └── realtime_seeds.jsonl           # Seed news
├── build.sh                           # One-command launcher
├── db-clean.sh                        # Data cleanup script
└── requirements.txt
```

## License

MIT
