<div align="center">

# OpenNews

Real-time financial news knowledge graph and impact scoring system.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![中文](https://img.shields.io/badge/lang-中文-red.svg)](README.zh.md)

</div>

---

<p align="center">
  <img src="docs/view.png" alt="OpenNews Web Panel" width="820" />
</p>

## Contents

- [Overview](#overview)
- [Pipeline](#pipeline)
- [Quick Start (Docker)](#quick-start-docker)
- [Local Setup](#local-setup)
- [Web APIs](#web-apis)
  - [Share Snapshot API (PNG)](#share-snapshot-api-png)
- [Configuration](#configuration)
- [News Input](#news-input)
- [Project Structure](#project-structure)
- [License](#license)

## Overview

OpenNews is a LangGraph-based pipeline for financial news analysis.
It ingests multi-source news, runs NLP and impact scoring, then persists results to PostgreSQL and Neo4j, with a built-in web dashboard for real-time filtering and inspection.

### Highlights

- Multi-source ingestion (NewsNow API + JSONL seeds)
- FinBERT embedding + online topic clustering
- DeBERTa zero-shot classification
- 7-dimension feature extraction
- DK-CoT impact score (`0-100`)
- Redis temporal memory (rolling window)
- Bilingual topic labels (`zh`/`en`) with retry
- Web dashboard + share snapshot generation

## Pipeline

```text
retry_labels → fetch_news → embed → extract_entities ─┬→ topics ──────────┐
                                                      ├→ classify ────────┤
                                                      └→ extract_features ┘
                                                              ↓
                                                        build_payload → dump_output
                                                              ↓
                                                        memory_ingest → update_trends
                                                              ↓
                                                           report → write_graph → END
```

## Quick Start (Docker)

> Recommended for first run.

```bash
# Start full stack (PostgreSQL + Neo4j + Redis + backend + web)
docker compose -f docker/docker-compose.yml up -d

# Check status
docker compose -f docker/docker-compose.yml ps

# Backend logs
docker compose -f docker/docker-compose.yml logs -f backend

# Stop
docker compose -f docker/docker-compose.yml down
```

Web dashboard: `http://localhost:8080` (or `WEB_PORT`).

## Local Setup

```bash
git clone https://github.com/user/opennews.git && cd opennews
python3.10 -m venv .venv
source .venv/bin/activate

# CPU torch wheel comes from the PyTorch index
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

If you use the PNG share API locally, install browser runtime once:

```bash
pip install playwright
playwright install chromium
```

### Local run (without Docker for app process)

```bash
# Infra services (example)
docker run -d --name opennews-pg -p 5432:5432 -e POSTGRES_PASSWORD=123456 -e POSTGRES_DB=opennews postgres:16-alpine
docker run -d --name opennews-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/Aa123456 neo4j:5-community
docker run -d --name opennews-redis -p 6379:6379 redis:7-alpine

# Run pipeline
PYTHONPATH=src python -m opennews.main

# Build frontend
cd web && npm install && npx vite build && cd ..

# Run web server
PYTHONPATH=src python web/server.py --port 8080
```

## Web APIs

### Core Data APIs

| Endpoint | Description |
|---|---|
| `GET /api/batches` | List all batches |
| `GET /api/batches/latest` | Load latest batch records |
| `GET /api/batches/<id>` | Load records by batch ID |
| `GET /api/records?hours=N&page=P&score_lo=X&score_hi=Y` | Query recent records with score range |

### Share Snapshot API (PNG)

`GET /api/share/default`

Returns a **PNG image** (`Content-Type: image/png`) rendered with the same layout as the frontend share card.

#### Query Parameters

| Param | Type | Default | Notes |
|---|---:|---:|---|
| `hours` | float | `24` | Time window in hours (`0.1 ~ 8760`) |
| `score_lo` | float | `50` | Lower score bound (`0 ~ 100`) |
| `score_hi` | float | `100` | Upper score bound (`0 ~ 100`) |
| `lang` | string | `zh` | `zh` or `en` |
| `limit` | int | `5` | Number of top topics (`1 ~ 50`) |
| `width` | int | `390` | Card width (`200 ~ 1200`) |
| `pixel_ratio` | float | `2` | Output scale (`0.5 ~ 4`) |
| `background` | string | `#f5f6f8` | Card background color |
| `cache` | bool | `true` | Read/write cache |
| `refresh` | bool | `false` | Force re-render and refresh cache |

#### Cache behavior

- `refresh=true`: always re-render.
- `cache=true` and `refresh=false`: try memory/disk cache first.
- `cache=false&refresh=false`: render once without cache read/write.

#### Examples

```bash
# Default snapshot
curl "http://localhost:8080/api/share/default" -o share.png

# English snapshot with custom filter
curl "http://localhost:8080/api/share/default?lang=en&hours=48&score_lo=60&score_hi=95&limit=3" -o share-en.png

# Force refresh
curl "http://localhost:8080/api/share/default?refresh=true" -o share-fresh.png
```

## Configuration

All settings can be overridden by environment variables.

### Core

| Variable | Default | Description |
|---|---|---|
| `NEWS_POLL_INTERVAL_MIN` | `5` | Polling interval (minutes) |
| `BATCH_SIZE` | `32` | Max fetched items per cycle |
| `EMBEDDING_MODEL` | `ProsusAI/finbert` | Embedding model |
| `NER_MODEL` | `dslim/bert-base-NER` | NER model |
| `CLASSIFIER_MODEL` | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | Zero-shot model |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis connection |
| `MEMORY_WINDOW_DAYS` | `30` | Temporal memory window |
| `PG_HOST` / `PG_PORT` / `PG_USER` / `PG_PASSWORD` / `PG_DATABASE` | `127.0.0.1` / `5432` / `postgres` / `123456` / `opennews` | PostgreSQL |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | `bolt://127.0.0.1:7687` / `neo4j` / `Aa123456` | Neo4j |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | — / — / `gpt-4o-mini` | Topic refinement LLM |

### Share API

| Variable | Default | Description |
|---|---|---|
| `SHARE_API_ENABLED` | `true` | Enable `/api/share/default` |
| `SHARE_SCHEDULER_ENABLED` | `true` | Enable periodic default-cache warmup |
| `SHARE_REFRESH_MINUTES` | `30` | Refresh interval for default cache |
| `SHARE_DEFAULT_HOURS` | `24` | Default `hours` |
| `SHARE_DEFAULT_SCORE_LO` | `50` | Default `score_lo` |
| `SHARE_DEFAULT_SCORE_HI` | `100` | Default `score_hi` |
| `SHARE_DEFAULT_LANG` | `zh` | Default language |
| `SHARE_DEFAULT_LIMIT` | `5` | Default topic count |
| `SHARE_DEFAULT_WIDTH` | `390` | Default output width |
| `SHARE_DEFAULT_PIXEL_RATIO` | `2` | Default output scale |
| `SHARE_DEFAULT_BACKGROUND` | `#f5f6f8` | Default background |
| `SHARE_CACHE_DIR` | `data/share` | PNG cache directory |
| `SHARE_RENDER_TIMEOUT_MS` | `15000` | Render timeout |

## News Input

### NewsNow API

Configure in `config/sources.yaml`:

```yaml
newsnow:
  - url: https://newsnow.busiyi.world/api/s/entire
    sources:
      - wallstreetcn-news
      - cls-telegraph
      - 36kr-quick
```

### Seed file

Write one JSON object per line to `seeds/realtime_seeds.jsonl`:

```jsonl
{"news_id":"seed-001","title":"Fed hints at slower rate cuts","content":"Officials signal a cautious approach.","source":"seed","url":"seed://seed-001","published_at":"2026-03-09T07:30:00+00:00"}
```

## Project Structure

```text
opennews/
├── src/opennews/            # pipeline, DB, graph, NLP, scheduler
├── web/                     # frontend + web/server.py
├── config/                  # llm.yaml, sources.yaml
├── docker/                  # compose and volumes
├── seeds/                   # JSONL seed news
├── build.sh                 # one-command launcher
├── db-clean.sh              # cleanup script
└── requirements.txt
```

## License

MIT

## Community

- [LinuxDO](https://linux.do)
