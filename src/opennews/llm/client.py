"""OpenNews LLM Client — 通用 OpenAI 兼容客户端。"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "llm.yaml"


@dataclass(slots=True)
class LLMConfig:
    """LLM 连接与行为配置。"""
    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: int = 60
    topic_refine_enabled: bool = True
    topic_refine_max_retries: int = 2
    topic_refine_system_prompt: str = ""
    topic_refine_user_prompt_template: str = ""

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LLMConfig":
        """从 YAML 文件加载配置，环境变量可覆盖关键字段。"""
        cfg_path = Path(path) if path else _DEFAULT_CONFIG_PATH
        raw: dict = {}
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            logger.info("loaded LLM config from %s", cfg_path)
        else:
            logger.warning("LLM config not found at %s, using defaults", cfg_path)

        # 环境变量覆盖
        api_key = os.getenv("LLM_API_KEY") or raw.get("api_key")
        base_url = os.getenv("LLM_BASE_URL") or raw.get("base_url")
        model = os.getenv("LLM_MODEL") or raw.get("model", "gpt-4o-mini")

        topic_refine = raw.get("topic_refine", {})

        return cls(
            provider=raw.get("provider", "openai"),
            base_url=base_url if base_url else None,
            api_key=api_key if api_key else None,
            model=model,
            temperature=float(raw.get("temperature", 0.1)),
            max_tokens=int(raw.get("max_tokens", 4096)),
            timeout=int(raw.get("timeout", 60)),
            topic_refine_enabled=raw.get("topic_refine_enabled", True),
            topic_refine_max_retries=int(raw.get("topic_refine_max_retries", 2)),
            topic_refine_system_prompt=topic_refine.get("system_prompt", ""),
            topic_refine_user_prompt_template=topic_refine.get("user_prompt_template", ""),
        )


class LLMClient:
    """OpenAI 兼容的 LLM 客户端。"""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.load()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            kwargs = {"api_key": self.config.api_key, "timeout": self.config.timeout}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            # 禁用 SDK 内部重试，由 chat() 方法统一管理重试逻辑
            kwargs["max_retries"] = 0
            # 覆盖 SDK 默认的 User-Agent（OpenAI/Python x.x.x），
            # 避免被 Cloudflare bot 检测拦截（error 1010 / 403）
            kwargs["default_headers"] = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            }
            self._client = OpenAI(**kwargs)
            logger.info("initialized LLM client: model=%s, base_url=%s",
                        self.config.model, self.config.base_url or "default")
        return self._client

    def chat(self, system: str, user: str, **kwargs) -> str:
        """发送一次 chat completion 请求，返回 assistant 回复文本。
        遇到 5xx / 429 错误时自动重试（指数退避，最多 3 次）。"""
        client = self._get_client()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=kwargs.get("temperature", self.config.temperature),
                    max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                err_str = str(e)
                is_retryable = any(code in err_str for code in ("502", "503", "429"))
                if is_retryable and attempt < max_retries - 1:
                    wait = 3 * (2 ** attempt)  # 3s, 6s, 12s
                    logger.warning("LLM request failed (attempt %d/%d), retrying in %ds: %s",
                                   attempt + 1, max_retries, wait, err_str[:120])
                    time.sleep(wait)
                    continue
                raise
