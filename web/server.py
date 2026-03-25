#!/usr/bin/env python3
"""OpenNews Web Server — 轻量 HTTP 服务器。

同时提供：
  1. web/ 目录下的前端静态文件
  2. /api/batches        — 列出所有批次（按时间倒序）
  3. /api/batches/latest — 读取最新批次的全部记录
  4. /api/batches/<id>   — 读取指定批次的全部记录
  5. /api/share/default  — 返回默认参数下的分享图片 (SVG)

启动方式：
  python web/server.py [--port 8080]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

logger = logging.getLogger("opennews.web")

WEB_DIR = Path(__file__).resolve().parent / "dist"

# 将项目 src 加入 sys.path，以便导入 opennews 包
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _db():
    """延迟导入 db 模块（首次调用时初始化连接池）。"""
    from opennews import db
    return db


# ── 分享图缓存 ────────────────────────────────────────────
_share_cache_lock = threading.Lock()
_share_cache_svg: str | None = None
_share_scheduler: object | None = None


def _generate_share_cache() -> None:
    """生成默认分享图并缓存到内存和磁盘。"""
    global _share_cache_svg
    try:
        from opennews.config import settings
        from opennews.share.service import build_share_data
        from opennews.share.svg_renderer import render_svg

        data = build_share_data()
        svg = render_svg(data)

        with _share_cache_lock:
            _share_cache_svg = svg

        # 写入磁盘缓存
        cache_path = Path(settings.share_cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(svg, encoding="utf-8")
        logger.info("share cache updated: %s (%d bytes)", cache_path, len(svg))
    except Exception:
        logger.exception("failed to generate share cache")


def _init_share_scheduler() -> None:
    """根据配置初始化分享图定时刷新。"""
    global _share_scheduler
    from opennews.config import settings

    if not settings.share_api_enabled:
        logger.info("share API disabled, skipping share cache init")
        return

    # 启动时先生成一次
    _generate_share_cache()

    if not settings.share_scheduler_enabled:
        logger.info("share scheduler disabled, cache generated once")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _generate_share_cache,
            "interval",
            minutes=settings.share_refresh_minutes,
        )
        scheduler.start()
        _share_scheduler = scheduler
        logger.info(
            "share scheduler started, refresh every %d min",
            settings.share_refresh_minutes,
        )
    except ImportError:
        # APScheduler 不可用时用简单的 Timer 循环
        def _timer_loop():
            import time
            while True:
                time.sleep(settings.share_refresh_minutes * 60)
                _generate_share_cache()

        t = threading.Thread(target=_timer_loop, daemon=True)
        t.start()
        _share_scheduler = t
        logger.info(
            "share timer started (no APScheduler), refresh every %d min",
            settings.share_refresh_minutes,
        )


class OpenNewsHandler(SimpleHTTPRequestHandler):
    """扩展静态文件服务器，增加 /api/* 路由。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    # ── 路由分发 ──────────────────────────────────────────
    def do_GET(self):
        if self.path == "/api/batches":
            self._handle_list()
        elif self.path == "/api/batches/latest":
            self._handle_latest()
        elif self.path.startswith("/api/batches/"):
            raw = self.path[len("/api/batches/"):]
            self._handle_read(raw)
        elif self.path.startswith("/api/records"):
            self._handle_records()
        elif self.path == "/api/share/default":
            self._handle_share_default()
        else:
            super().do_GET()

    # ── API handlers ──────────────────────────────────────
    def _handle_list(self):
        try:
            db = _db()
            db.ensure_schema()
            batches = db.list_batches()
            data = [
                {
                    "batch_id": b["batch_id"],
                    "batch_ts": b["batch_ts"],
                    "record_count": b["record_count"],
                    "created_at": b["created_at"].isoformat() if b.get("created_at") else None,
                }
                for b in batches
            ]
            self._json_response(data)
        except Exception as e:
            logger.exception("list batches failed")
            self._json_error(str(e), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_latest(self):
        try:
            db = _db()
            db.ensure_schema()
            records = db.get_latest_batch_records()
            self._json_response(records)
        except Exception as e:
            logger.exception("get latest batch failed")
            self._json_error(str(e), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_read(self, raw: str):
        try:
            batch_id = int(raw)
        except ValueError:
            self._json_error("invalid batch id", HTTPStatus.BAD_REQUEST)
            return
        try:
            db = _db()
            records = db.get_batch_records(batch_id)
            if not records:
                self._json_error("batch not found", HTTPStatus.NOT_FOUND)
                return
            self._json_response(records)
        except Exception as e:
            logger.exception("get batch %d failed", batch_id)
            self._json_error(str(e), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_records(self):
        """GET /api/records?hours=N&page=P&score_lo=X&score_hi=Y — 获取最近 N 小时内的记录（按主题分页）。"""
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(self.path).query)
        try:
            hours = float(qs.get("hours", ["24"])[0])
        except (ValueError, IndexError):
            hours = 24.0
        try:
            page = int(qs.get("page", ["1"])[0])
        except (ValueError, IndexError):
            page = 1
        try:
            score_lo = float(qs.get("score_lo", ["0"])[0])
        except (ValueError, IndexError):
            score_lo = 0.0
        try:
            score_hi = float(qs.get("score_hi", ["100"])[0])
        except (ValueError, IndexError):
            score_hi = 100.0
        try:
            db = _db()
            result = db.get_records_since(hours, page=page, score_lo=score_lo, score_hi=score_hi)
            self._json_response(result)
        except Exception as e:
            logger.exception("get records since %s hours failed", hours)
            self._json_error(str(e), HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_share_default(self):
        """GET /api/share/default — 返回默认参数下的分享图片 (SVG)。"""
        from opennews.config import settings

        if not settings.share_api_enabled:
            self._json_error("share API is disabled", HTTPStatus.NOT_FOUND)
            return

        global _share_cache_svg
        svg = None
        with _share_cache_lock:
            svg = _share_cache_svg

        # 若缓存为空，尝试即时生成一次
        if svg is None:
            _generate_share_cache()
            with _share_cache_lock:
                svg = _share_cache_svg

        if svg is None:
            self._json_error("no share image available", HTTPStatus.SERVICE_UNAVAILABLE)
            return

        body = svg.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(body)

    # ── 响应工具 ──────────────────────────────────────────
    def _json_response(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, msg: str, status: HTTPStatus):
        self._json_response({"error": msg}, status)

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description="OpenNews Web Server")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认 8080)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    # 预检 PG 连接
    try:
        db = _db()
        db.ensure_schema()
        logger.info("PostgreSQL connection OK")
    except Exception:
        logger.exception("PostgreSQL connection failed — server will start but API may error")

    # 初始化分享图缓存与定时刷新
    try:
        _init_share_scheduler()
    except Exception:
        logger.exception("share scheduler init failed — share API may be unavailable")

    server = HTTPServer(("0.0.0.0", args.port), OpenNewsHandler)
    logger.info("OpenNews Web Server listening on http://localhost:%d", args.port)
    logger.info("Serving static files from: %s", WEB_DIR)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
