#!/usr/bin/env python3
"""OpenNews Web Server — 轻量 HTTP 服务器。

同时提供：
  1. web/ 目录下的前端静态文件
  2. /api/batches        — 列出所有批次（按时间倒序）
  3. /api/batches/latest — 读取最新批次的全部记录
  4. /api/batches/<id>   — 读取指定批次的全部记录
  5. /api/share/default  — 返回分享截图 (PNG)

启动方式：
  python web/server.py [--port 8080]
"""
from __future__ import annotations

import argparse
import hashlib
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


# ── 分享图 PNG 缓存 ──────────────────────────────────────
_share_cache_lock = threading.Lock()
_share_png_cache: dict[str, bytes] = {}  # key -> PNG bytes
_share_scheduler: object | None = None


def _make_share_cache_key(
    hours: float,
    score_lo: float,
    score_hi: float,
    lang: str,
    limit: int,
    width: int,
    pixel_ratio: float,
    background: str,
) -> str:
    """根据规范化参数生成稳定的缓存键。"""
    raw = f"{hours:.1f}|{score_lo:.1f}|{score_hi:.1f}|{lang}|{limit}|{width}|{pixel_ratio:.1f}|{background}"
    return hashlib.md5(raw.encode()).hexdigest()


def _render_share_png(
    hours: float,
    score_lo: float,
    score_hi: float,
    lang: str,
    limit: int,
    width: int,
    pixel_ratio: float,
    background: str,
    timeout_ms: int,
) -> bytes:
    """即时渲染一张分享 PNG。"""
    from opennews.share.service import build_share_data
    from opennews.share.html_renderer import render_html
    from opennews.share.png_renderer import render_png

    data = build_share_data(
        hours=hours,
        score_lo=score_lo,
        score_hi=score_hi,
        lang=lang,
        limit=limit,
    )
    html_content = render_html(data, width=width, background=background)
    return render_png(
        html_content,
        width=width,
        pixel_ratio=pixel_ratio,
        timeout_ms=timeout_ms,
    )


def _get_or_render_share_png(
    hours: float,
    score_lo: float,
    score_hi: float,
    lang: str,
    limit: int,
    width: int,
    pixel_ratio: float,
    background: str,
    timeout_ms: int,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> bytes:
    """获取分享 PNG，支持缓存策略。"""
    key = _make_share_cache_key(
        hours, score_lo, score_hi, lang, limit, width, pixel_ratio, background,
    )

    # 非强刷时尝试读缓存
    if use_cache and not force_refresh:
        with _share_cache_lock:
            cached = _share_png_cache.get(key)
        if cached is not None:
            logger.debug("share cache hit: %s", key[:8])
            return cached

        # 尝试磁盘缓存
        from opennews.config import settings
        disk_path = Path(settings.share_cache_dir) / f"{key}.png"
        if disk_path.exists():
            png_bytes = disk_path.read_bytes()
            with _share_cache_lock:
                _share_png_cache[key] = png_bytes
            logger.debug("share disk cache hit: %s", key[:8])
            return png_bytes

    # 渲染
    png_bytes = _render_share_png(
        hours, score_lo, score_hi, lang, limit,
        width, pixel_ratio, background, timeout_ms,
    )

    # 写缓存
    if use_cache or force_refresh:
        with _share_cache_lock:
            _share_png_cache[key] = png_bytes
        try:
            from opennews.config import settings
            cache_dir = Path(settings.share_cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{key}.png").write_bytes(png_bytes)
            logger.info("share cache written: %s (%d bytes)", key[:8], len(png_bytes))
        except Exception:
            logger.exception("failed to write share disk cache")

    return png_bytes


def _generate_default_share_cache() -> None:
    """预热默认参数下的分享 PNG 缓存。"""
    try:
        from opennews.config import settings
        _get_or_render_share_png(
            hours=settings.share_default_hours,
            score_lo=settings.share_default_score_lo,
            score_hi=settings.share_default_score_hi,
            lang=settings.share_default_lang,
            limit=settings.share_default_limit,
            width=settings.share_default_width,
            pixel_ratio=settings.share_default_pixel_ratio,
            background=settings.share_default_background,
            timeout_ms=settings.share_render_timeout_ms,
            use_cache=True,
            force_refresh=True,
        )
        logger.info("default share PNG cache warmed up")
    except Exception:
        logger.exception("failed to generate default share cache")


def _init_share_scheduler() -> None:
    """根据配置初始化分享图定时刷新。"""
    global _share_scheduler
    from opennews.config import settings

    if not settings.share_api_enabled:
        logger.info("share API disabled, skipping share cache init")
        return

    # 启动时先生成一次
    _generate_default_share_cache()

    if not settings.share_scheduler_enabled:
        logger.info("share scheduler disabled, cache generated once")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _generate_default_share_cache,
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
                _generate_default_share_cache()

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
        elif self.path.startswith("/api/share/default"):
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
        """GET /api/share/default — 返回分享截图 (PNG)。

        查询参数（均可选，带默认值）：
          数据参数:
            hours      — 时间范围（小时），默认 24
            score_lo   — 最低分，默认 50
            score_hi   — 最高分，默认 100
            lang       — 语言 zh|en，默认 zh
            limit      — 热门主题条数，默认 5
          渲染参数:
            width       — 卡片宽度（px），默认 390
            pixel_ratio — 设备像素比，默认 2
            background  — 背景色，默认 #f5f6f8
          缓存控制:
            cache       — 是否使用缓存 true|false，默认 true
            refresh     — 是否强制重绘 true|false，默认 false
        """
        from urllib.parse import parse_qs, urlparse
        from opennews.config import settings

        if not settings.share_api_enabled:
            self._json_error("share API is disabled", HTTPStatus.NOT_FOUND)
            return

        qs = parse_qs(urlparse(self.path).query)

        # ── 解析参数 ─────────────────────────────────────
        def _float(key: str, default: float, lo: float = 0, hi: float = 1e9) -> float | None:
            try:
                v = float(qs.get(key, [str(default)])[0])
                if v < lo or v > hi:
                    return None
                return v
            except (ValueError, IndexError):
                return None

        def _int(key: str, default: int, lo: int = 1, hi: int = 10000) -> int | None:
            try:
                v = int(qs.get(key, [str(default)])[0])
                if v < lo or v > hi:
                    return None
                return v
            except (ValueError, IndexError):
                return None

        def _bool(key: str, default: bool) -> bool:
            raw = qs.get(key, [str(default).lower()])[0].lower()
            return raw in ("true", "1", "yes")

        hours = _float("hours", settings.share_default_hours, lo=0.1, hi=8760)
        score_lo = _float("score_lo", settings.share_default_score_lo, lo=0, hi=100)
        score_hi = _float("score_hi", settings.share_default_score_hi, lo=0, hi=100)
        lang_raw = qs.get("lang", [settings.share_default_lang])[0].lower()
        limit = _int("limit", settings.share_default_limit, lo=1, hi=50)
        width = _int("width", settings.share_default_width, lo=200, hi=1200)
        pixel_ratio = _float("pixel_ratio", settings.share_default_pixel_ratio, lo=0.5, hi=4)
        background = qs.get("background", [settings.share_default_background])[0]
        use_cache = _bool("cache", True)
        force_refresh = _bool("refresh", False)

        # ── 参数校验 ─────────────────────────────────────
        errors = []
        if hours is None:
            errors.append("hours must be between 0.1 and 8760")
        if score_lo is None:
            errors.append("score_lo must be between 0 and 100")
        if score_hi is None:
            errors.append("score_hi must be between 0 and 100")
        if score_lo is not None and score_hi is not None and score_lo > score_hi:
            errors.append("score_lo must be <= score_hi")
        if lang_raw not in ("zh", "en"):
            errors.append("lang must be 'zh' or 'en'")
        if limit is None:
            errors.append("limit must be between 1 and 50")
        if width is None:
            errors.append("width must be between 200 and 1200")
        if pixel_ratio is None:
            errors.append("pixel_ratio must be between 0.5 and 4")

        if errors:
            self._json_error("; ".join(errors), HTTPStatus.BAD_REQUEST)
            return

        # ── 渲染 / 缓存 ─────────────────────────────────
        try:
            png_bytes = _get_or_render_share_png(
                hours=hours,
                score_lo=score_lo,
                score_hi=score_hi,
                lang=lang_raw,
                limit=limit,
                width=width,
                pixel_ratio=pixel_ratio,
                background=background,
                timeout_ms=settings.share_render_timeout_ms,
                use_cache=use_cache,
                force_refresh=force_refresh,
            )
        except Exception as e:
            logger.exception("share render failed")
            self._json_error(f"render failed: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # ── 返回 PNG ─────────────────────────────────────
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if use_cache and not force_refresh:
            self.send_header("Cache-Control", "public, max-age=60")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(png_bytes)

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
        # 清理浏览器
        try:
            from opennews.share.png_renderer import shutdown as shutdown_browser
            shutdown_browser()
        except Exception:
            pass


if __name__ == "__main__":
    main()
