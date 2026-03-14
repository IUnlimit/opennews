"""OpenNews 新闻源配置加载 — 启动时自动检测并创建默认配置。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"

_DEFAULT_CONTENT = """\
# ═══════════════════════════════════════════════════════════
#  OpenNews — 新闻源配置
#  程序启动时自动检测，不存在则创建此默认文件
# ═══════════════════════════════════════════════════════════

# 当前仅支持 newsnow 类型数据源
# 每个 url 对应一个 NewsNow 兼容 API 端点，sources 为该端点下的频道列表

newsnow:
  - url: https://newsnow.busiyi.world/api/s/entire
    sources:
      - wallstreetcn-news
"""


@dataclass(slots=True)
class NewsNowEndpoint:
    """单个 NewsNow API 端点配置。"""
    url: str
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourcesConfig:
    """新闻源总配置。"""
    newsnow: list[NewsNowEndpoint] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SourcesConfig":
        """从 YAML 加载配置，文件不存在时自动创建默认配置。"""
        cfg_path = Path(path) if path else _DEFAULT_CONFIG_PATH

        if not cfg_path.exists():
            logger.info("sources config not found, creating default at %s", cfg_path)
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(_DEFAULT_CONTENT, encoding="utf-8")

        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        logger.info("loaded sources config from %s", cfg_path)

        endpoints = []
        for item in raw.get("newsnow", []):
            url = item.get("url", "")
            sources = item.get("sources", [])
            if url:
                endpoints.append(NewsNowEndpoint(url=url, sources=sources))

        return cls(newsnow=endpoints)
