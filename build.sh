#!/usr/bin/env bash
set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ── 配置（可通过环境变量覆盖） ────────────────────────────
NEO4J_HOST="${NEO4J_HOST:-127.0.0.1}"
NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-7687}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
WEB_PORT="${WEB_PORT:-8081}"

# 项目根目录 = 脚本所在目录
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

BACKEND_PID=""
FRONTEND_PID=""

# ── 清理函数 ──────────────────────────────────────────────
cleanup() {
    echo ""
    info "正在关闭服务..."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null && info "前端已停止 (PID $FRONTEND_PID)"
    [ -n "$BACKEND_PID" ]  && kill "$BACKEND_PID"  2>/dev/null && info "后端已停止 (PID $BACKEND_PID)"
    wait 2>/dev/null
    info "已退出"
}
trap cleanup EXIT INT TERM

# ══════════════════════════════════════════════════════════
#  1. 依赖服务检查
# ══════════════════════════════════════════════════════════
info "检查依赖服务..."

# ── Neo4j (Bolt 端口) ────────────────────────────────────
if (netstat -tlnp 2>&1 || true) | grep -q ":${NEO4J_BOLT_PORT}\b"; then
    ok "Neo4j 已就绪 ($NEO4J_HOST:$NEO4J_BOLT_PORT)"
else
    fail "Neo4j 未启动 — 请先运行: cd docker/neo4j && docker compose up -d"
fi

# ── Redis ─────────────────────────────────────────────────
if (netstat -tlnp 2>&1 || true) | grep -q ":${REDIS_PORT}\b"; then
    ok "Redis 已就绪 ($REDIS_HOST:$REDIS_PORT)"
else
    fail "Redis 未启动 — 请先运行: docker run -d --name opennews-redis -p 6379:6379 redis:7"
fi

# ── PostgreSQL ────────────────────────────────────────────
if (netstat -tlnp 2>&1 || true) | grep -q ":${PG_PORT}\b"; then
    ok "PostgreSQL 已就绪 ($PG_HOST:$PG_PORT)"
else
    fail "PostgreSQL 未启动 — 请确保 PostgreSQL 运行在 $PG_HOST:$PG_PORT"
fi

echo ""

# ══════════════════════════════════════════════════════════
#  2. 安装 Python 依赖
# ══════════════════════════════════════════════════════════
info "检查 Python 依赖..."
if pip install -q -r "$ROOT/requirements.txt" 2>&1 | tail -1; then
    ok "Python 依赖已就绪"
else
    fail "依赖安装失败，请检查 requirements.txt"
fi

# ══════════════════════════════════════════════════════════
#  3. 初始化 PostgreSQL 数据库
# ══════════════════════════════════════════════════════════
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-123456}"
PG_DATABASE="${PG_DATABASE:-opennews}"

info "检查数据库 ${PG_DATABASE}..."
if PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
    -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "$PG_DATABASE"; then
    ok "数据库 ${PG_DATABASE} 已存在"
else
    info "创建数据库 ${PG_DATABASE}..."
    if PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" \
        -c "CREATE DATABASE ${PG_DATABASE};" 2>/dev/null; then
        ok "数据库 ${PG_DATABASE} 创建成功"
    else
        fail "无法创建数据库 ${PG_DATABASE}，请手动执行: psql -U $PG_USER -c \"CREATE DATABASE ${PG_DATABASE};\""
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════
#  4. 启动后端服务
# ══════════════════════════════════════════════════════════
info "启动后端流水线..."
PYTHONPATH="$ROOT/src" python -m opennews.main &
BACKEND_PID=$!
info "后端 PID: $BACKEND_PID"

# 等待后端正常启动（检测进程存活 + PG 建表完成）
info "等待后端初始化..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    # 进程挂了就直接退出
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        fail "后端进程异常退出，请检查日志"
    fi

    # 检测 PG 中 batches 表是否已创建（说明后端已完成初始化）
    if PGPASSWORD="${PG_PASSWORD:-123456}" psql -h "$PG_HOST" -p "$PG_PORT" \
        -U "${PG_USER:-postgres}" -d "${PG_DATABASE:-opennews}" \
        -c "SELECT 1 FROM batches LIMIT 0" >/dev/null 2>&1; then
        break
    fi

    sleep 2
    WAITED=$((WAITED + 2))
    printf "\r${CYAN}[INFO]${NC}  已等待 %ds / %ds..." "$WAITED" "$MAX_WAIT"
done
echo ""

if [ $WAITED -ge $MAX_WAIT ]; then
    warn "等待超时，后端可能仍在加载模型（首次启动需下载 ~1.5GB），前端将先行启动"
else
    ok "后端已就绪"
fi

# ══════════════════════════════════════════════════════════
#  5. 构建前端 Vue 项目
# ══════════════════════════════════════════════════════════
info "构建前端 Vue 项目..."
if [ ! -d "$ROOT/web/node_modules" ]; then
    info "安装前端依赖..."
    (cd "$ROOT/web" && npm install --silent) || fail "npm install 失败"
fi
(cd "$ROOT/web" && npx vite build) || fail "前端构建失败"
ok "前端构建完成 → web/dist/"

echo ""

# ══════════════════════════════════════════════════════════
#  6. 启动前端服务
# ══════════════════════════════════════════════════════════
info "启动前端 Web 服务 (端口 $WEB_PORT)..."
PYTHONPATH="$ROOT/src" python "$ROOT/web/server.py" --port "$WEB_PORT" &
FRONTEND_PID=$!
sleep 1

if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    ok "前端已启动 → http://localhost:$WEB_PORT"
else
    fail "前端启动失败，请检查端口 $WEB_PORT 是否被占用"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  OpenNews 已启动${NC}"
echo -e "${GREEN}  后端 PID: $BACKEND_PID${NC}"
echo -e "${GREEN}  前端地址: http://localhost:$WEB_PORT${NC}"
echo -e "${GREEN}  按 Ctrl+C 停止所有服务${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo ""

# 前台等待，Ctrl+C 触发 cleanup
wait
