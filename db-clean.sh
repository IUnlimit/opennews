#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-123456}"
PG_DATABASE="${PG_DATABASE:-opennews}"

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${YELLOW}════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  OpenNews 数据清理${NC}"
echo -e "${YELLOW}  将清除以下数据：${NC}"
echo -e "${YELLOW}    • PostgreSQL: reports, batch_records, batches${NC}"
echo -e "${YELLOW}    • Checkpoint: seeds/checkpoint.json${NC}"
echo -e "${YELLOW}════════════════════════════════════════════════${NC}"
echo ""

read -rp "确认清除所有数据？(y/N) " confirm
if [[ ! "$confirm" =~ ^[yY]$ ]]; then
    info "已取消"
    exit 0
fi

echo ""

# ── 清除 PostgreSQL ──────────────────────────────────────
info "清除 PostgreSQL 数据..."
if PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DATABASE" \
    -c "TRUNCATE reports, batch_records, batches RESTART IDENTITY CASCADE;" 2>/dev/null; then
    ok "PostgreSQL 数据已清除"
else
    warn "PostgreSQL 清除失败（数据库或表可能不存在）"
fi

# ── 清除 Checkpoint ──────────────────────────────────────
# 兼容多种运行方式：同时清除脚本目录和 CWD 下的 checkpoint
for cp in "$ROOT/seeds/checkpoint.json" "seeds/checkpoint.json"; do
    if [ -f "$cp" ]; then
        rm -f "$cp"
        ok "Checkpoint 已清除: $cp"
    fi
done

echo ""
ok "清理完成，重启服务后将从零开始拉取数据"
