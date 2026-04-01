"""将 HTML 字符串渲染为 PNG 字节流。

使用 Playwright Chromium 无头浏览器截图，确保与前端 DOM 截图视觉一致。
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

# 全局浏览器实例（进程级复用，避免每次请求都启动浏览器）
_browser_lock = threading.Lock()
_playwright_instance = None
_browser = None


def _ensure_browser():
    """延迟初始化 Playwright 浏览器（线程安全）。"""
    global _playwright_instance, _browser
    if _browser is not None:
        return _browser
    with _browser_lock:
        if _browser is not None:
            return _browser
        from playwright.sync_api import sync_playwright
        _playwright_instance = sync_playwright().start()
        _browser = _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--font-render-hinting=none",
            ],
        )
        logger.info("Playwright Chromium browser launched")
        return _browser


def render_png(
    html_content: str,
    *,
    width: int = 390,
    pixel_ratio: float = 2.0,
    timeout_ms: int = 15000,
) -> bytes:
    """将完整 HTML 文档渲染为 PNG 字节流。

    Args:
        html_content: 完整 HTML 文档字符串。
        width: 视口宽度（像素），对应前端 .share-card 宽度。
        pixel_ratio: 设备像素比，对应前端 html-to-image 的 pixelRatio。
        timeout_ms: 页面加载超时（毫秒）。

    Returns:
        PNG 图片的字节流。
    """
    browser = _ensure_browser()
    page = browser.new_page(
        viewport={"width": width, "height": 800},
        device_scale_factor=pixel_ratio,
    )
    try:
        page.set_content(html_content, wait_until="load", timeout=timeout_ms)

        # 定位 .share-card 元素截图（与前端 domToPngBlob 对齐）
        card = page.query_selector(".share-card")
        if card is None:
            # 回退：全页截图
            logger.warning("share-card element not found, falling back to full page screenshot")
            return page.screenshot(type="png", full_page=True)

        return card.screenshot(type="png")
    finally:
        page.close()


def shutdown():
    """关闭全局浏览器实例（进程退出时调用）。"""
    global _playwright_instance, _browser
    with _browser_lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright_instance is not None:
            try:
                _playwright_instance.stop()
            except Exception:
                pass
            _playwright_instance = None
