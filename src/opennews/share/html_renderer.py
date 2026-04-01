"""将 ShareData 渲染为与前端 ShareSnapshot.vue 视觉一致的静态 HTML。

生成的 HTML 是一个完整文档，内联了所有 CSS，可直接被无头浏览器截图。
模板结构、class 名、样式值均严格对齐：
  - web/src/components/ShareSnapshot.vue
  - web/src/style.css (.share-card / .sc-* 部分)
"""
from __future__ import annotations

import html
import math
from datetime import datetime


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _fmt_time(iso: str) -> str:
    """格式化 generatedAt 为 zh-CN 风格。"""
    try:
        d = datetime.fromisoformat(iso)
        return d.strftime("%Y/%m/%d %H:%M")
    except Exception:
        return iso[:19]


def _level_color(level: str) -> str:
    if level == "高":
        return "#ef4444"
    if level == "中":
        return "#f59e0b"
    return "#22c55e"


# ── 内联 CSS（严格对齐 style.css .share-card / .sc-* 部分） ─
_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { margin: 0; padding: 0; background: transparent; }
.share-card {
  width: {width}px;
  background: {background};
  border-radius: 12px;
  padding: 24px;
  font-family: 'Noto Sans SC', -apple-system, sans-serif;
  color: #374151;
  overflow: hidden;
}
.sc-brand { text-align: center; margin-bottom: 4px; }
.sc-logo {
  display: flex; align-items: center; justify-content: center;
  gap: 8px; margin-bottom: 4px;
}
.sc-logo-text {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700; font-size: 16px;
  letter-spacing: 3px; color: #2563eb;
}
.sc-subtitle {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; letter-spacing: 2px; color: #6b7280;
}
.sc-time {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px; color: #6b7280; margin-top: 4px;
}
.sc-divider { height: 1px; background: #dde1e8; margin: 12px 0; }
.sc-summary {
  text-align: center; font-size: 12px;
  color: #374151; margin-bottom: 4px;
}
.sc-metrics {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 6px; margin: 12px 0;
}
.sc-metric-box {
  background: #ffffff; border: 1px solid #dde1e8;
  border-radius: 6px; padding: 8px 4px; text-align: center;
}
.sc-metric-val {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700; font-size: 15px; color: #111827;
}
.sc-metric-label { font-size: 9px; color: #6b7280; margin-top: 2px; }
.sc-chart-area {
  display: flex; align-items: center; gap: 12px; margin: 10px 0;
}
.sc-donut-wrap { flex-shrink: 0; }
.sc-bars { flex: 1; display: flex; flex-direction: column; gap: 7px; }
.sc-bar-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px; font-weight: 600; display: block; margin-bottom: 2px;
}
.sc-bar-track { height: 11px; border-radius: 3px; overflow: hidden; }
.sc-bar-fill {
  height: 100%; border-radius: 3px; opacity: .75; min-width: 2px;
}
.sc-news-section { margin: 4px 0; }
.sc-news-title {
  font-weight: 600; font-size: 11px; color: #111827; margin-bottom: 8px;
}
.sc-news-row {
  display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px;
}
.sc-news-score {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700; font-size: 13px; min-width: 36px;
  text-align: right; flex-shrink: 0; line-height: 1.3;
}
.sc-news-info { flex: 1; min-width: 0; }
.sc-news-headline {
  font-size: 11px; color: #374151; line-height: 1.4;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sc-news-meta {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px; color: #6b7280; margin-top: 2px;
}
.sc-footer { text-align: center; }
.sc-footer-note { font-size: 9px; color: #6b7280; margin-bottom: 6px; }
.sc-footer-brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600; font-size: 9px;
  letter-spacing: 2px; color: #2563eb;
}
"""


def render_html(
    data: dict,
    *,
    width: int = 390,
    background: str = "#f5f6f8",
) -> str:
    """将 build_share_data() 的输出渲染为完整 HTML 文档。"""
    lang = data.get("lang", "zh")
    is_zh = lang == "zh"

    generated_time = _fmt_time(data.get("generatedAt", ""))
    scope_text = _esc(data.get("scopeText", ""))
    score_range = _esc(data.get("scoreRange", "0–100"))

    filtered_count = data.get("filteredCount", 0)
    filtered_ratio = data.get("filteredRatio", 0.0)
    above75 = data.get("above75", 0)
    total_items = data.get("totalItems", 0)

    fl = data.get("filteredLevels", {"高": 0, "中": 0, "低": 0})
    fl_total = (fl.get("高", 0) + fl.get("中", 0) + fl.get("低", 0)) or 1

    top_topics = data.get("topTopics", [])

    # ── 环图 SVG 计算（与前端 ShareSnapshot.vue 一致） ────
    circumference = 2 * math.pi * 28
    ratio_clamped = min(1.0, max(0.0, filtered_ratio / 100))
    dash = ratio_clamped * circumference
    dash_array = f"{dash:.1f} {(circumference - dash):.1f}"
    dash_offset = f"{(circumference * 0.25):.1f}"

    # ── 堆叠条数据 ───────────────────────────────────────
    levels_data = [
        ("高", "High", fl.get("高", 0), "#ef4444", "#fde8e8"),
        ("中", "Mid", fl.get("中", 0), "#f59e0b", "#fef3cd"),
        ("低", "Low", fl.get("低", 0), "#22c55e", "#d1fae5"),
    ]

    css = _CSS.replace("{width}", str(width)).replace("{background}", background)

    # ── 构建 HTML ────────────────────────────────────────
    parts: list[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<style>{css}</style>
</head>
<body>
<div class="share-card">""")

    # 1. 品牌头部
    parts.append("""<div class="sc-brand">
  <div class="sc-logo">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="4" width="18" height="16" rx="2" stroke="#2563eb" stroke-width="1.8"/>
      <path d="M7 8H17" stroke="#2563eb" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M7 12H17" stroke="#2563eb" stroke-width="1.8" stroke-linecap="round"/>
      <path d="M7 16H13" stroke="#2563eb" stroke-width="1.8" stroke-linecap="round"/>
      <circle cx="17" cy="16" r="1.4" fill="#2563eb"/>
    </svg>
    <span class="sc-logo-text">OPENNEWS</span>
  </div>""")
    parts.append(f'  <div class="sc-subtitle">{"新闻影响快照" if is_zh else "IMPACT SNAPSHOT"}</div>')
    parts.append(f'  <div class="sc-time">{_esc(generated_time)}</div>')
    parts.append("</div>")

    # 分隔线
    parts.append('<div class="sc-divider"></div>')

    # 2. 筛选摘要
    parts.append(f'<div class="sc-summary">{scope_text}  |  {"评分" if is_zh else "Score"} {score_range}</div>')

    # 3. 核心指标 1x4
    metrics = [
        (str(filtered_count), "命中" if is_zh else "Filtered"),
        (f"{filtered_ratio:.1f}%", "占比" if is_zh else "Ratio"),
        (str(above75), "高影响" if is_zh else "High"),
        (str(total_items), "总数" if is_zh else "Total"),
    ]
    parts.append('<div class="sc-metrics">')
    for val, label in metrics:
        parts.append(f"""  <div class="sc-metric-box">
    <div class="sc-metric-val">{_esc(val)}</div>
    <div class="sc-metric-label">{_esc(label)}</div>
  </div>""")
    parts.append("</div>")

    # 4. 图表区：环图 + 堆叠条
    parts.append('<div class="sc-chart-area">')
    # 环形图
    parts.append(f"""  <div class="sc-donut-wrap">
    <svg width="76" height="76" viewBox="0 0 76 76">
      <circle cx="38" cy="38" r="28" fill="none" stroke="#dde1e8" stroke-width="8"/>
      <circle cx="38" cy="38" r="28" fill="none" stroke="#2563eb" stroke-width="8"
        stroke-dasharray="{dash_array}" stroke-dashoffset="{dash_offset}"
        stroke-linecap="round"/>
      <text x="38" y="36" text-anchor="middle" dominant-baseline="middle"
        font-family="'JetBrains Mono', monospace" font-weight="700" font-size="12" fill="#111827">
        {filtered_ratio:.1f}%</text>
      <text x="38" y="49" text-anchor="middle"
        font-family="'Noto Sans SC', sans-serif" font-size="7" fill="#6b7280">
        {"筛选占比" if is_zh else "filtered"}</text>
    </svg>
  </div>""")

    # 堆叠条
    parts.append('  <div class="sc-bars">')
    for lv_zh, lv_en, count, color, bg in levels_data:
        pct = (count / fl_total) * 100
        label = lv_zh if is_zh else lv_en
        parts.append(f"""    <div class="sc-bar-row">
      <span class="sc-bar-label" style="color:{color}">{_esc(label)} {count}</span>
      <div class="sc-bar-track" style="background-color:{bg}">
        <div class="sc-bar-fill" style="width:{pct:.1f}%;background-color:{color}"></div>
      </div>
    </div>""")
    parts.append("  </div>")
    parts.append("</div>")

    # 分隔线
    parts.append('<div class="sc-divider"></div>')

    # 5. 主题列表
    if top_topics:
        parts.append('<div class="sc-news-section">')
        parts.append(f'  <div class="sc-news-title">{"热门主题" if is_zh else "Top Topics"}</div>')
        for topic in top_topics:
            score_color = _level_color(topic.get("topLevel", "低"))
            max_score = topic.get("maxScore", 0)
            headline = topic.get("labelZh" if is_zh else "labelEn", "")
            news_count = topic.get("newsCount", 0)
            parts.append(f"""  <div class="sc-news-row">
    <span class="sc-news-score" style="color:{score_color}">{max_score:.1f}</span>
    <div class="sc-news-info">
      <div class="sc-news-headline">{_esc(headline)}</div>
      <div class="sc-news-meta">{news_count} {"条新闻" if is_zh else "news"}</div>
    </div>
  </div>""")
        parts.append("</div>")

    # 6. 页脚
    parts.append('<div class="sc-divider"></div>')
    parts.append(f"""<div class="sc-footer">
  <div class="sc-footer-note">{"基于当前筛选条件生成" if is_zh else "Based on current filters"}</div>
  <div class="sc-footer-brand">OPENNEWS</div>
</div>""")

    parts.append("</div></body></html>")
    return "\n".join(parts)
