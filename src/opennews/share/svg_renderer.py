"""将分享数据渲染为 SVG 字符串。

生成一张 390x auto 的手机比例分享卡片，包含：
  1. 品牌头部
  2. 筛选摘要
  3. 核心指标 (2x2)
  4. 占比环图 + 高/中/低堆叠条
  5. Top N 新闻列表
  6. 页脚
"""
from __future__ import annotations

import html
from datetime import datetime


# ── 颜色常量 ──────────────────────────────────────────────
_BG = "#f5f6f8"
_CARD_BG = "#ffffff"
_TEXT = "#374151"
_TEXT_DIM = "#6b7280"
_TEXT_BRIGHT = "#111827"
_ACCENT = "#2563eb"
_BORDER = "#dde1e8"
_HIGH = "#ef4444"
_HIGH_BG = "#fde8e8"
_MID = "#f59e0b"
_MID_BG = "#fef3cd"
_LOW = "#22c55e"
_LOW_BG = "#d1fae5"

_CAT_COLORS = {
    "financial_market": "#3b82f6",
    "policy_regulation": "#a855f7",
    "company_event": "#f59e0b",
    "macro_economy": "#06b6d4",
    "industry_trend": "#10b981",
}

_CAT_LABELS = {
    "financial_market": "FINANCIAL",
    "policy_regulation": "POLICY",
    "company_event": "COMPANY",
    "macro_economy": "MACRO",
    "industry_trend": "INDUSTRY",
}

_LEVEL_COLORS = {"高": _HIGH, "中": _MID, "低": _LOW}
_LEVEL_BG = {"高": _HIGH_BG, "中": _MID_BG, "低": _LOW_BG}

W = 390
PAD = 24


def _esc(text: str) -> str:
    """XML 转义。"""
    return html.escape(str(text), quote=True)


def _truncate(text: str, max_len: int = 36) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "..."


def _source_name(src: str) -> str:
    if not src:
        return "—"
    if "wallstreetcn" in src:
        return "华尔街见闻"
    if "cls" in src:
        return "财联社"
    if "caixin" in src:
        return "财新"
    if "reuters" in src:
        return "Reuters"
    if "weibo" in src:
        return "微博"
    if "seed" in src:
        return "Seed"
    return src[:12]


def _fmt_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _level_color(level: str) -> str:
    return _LEVEL_COLORS.get(level, _LOW)


def render_svg(data: dict) -> str:
    """将 build_share_data() 的输出渲染为 SVG 字符串。"""
    lang = data.get("lang", "zh")
    is_zh = lang == "zh"

    parts: list[str] = []
    y = 0  # 当前 y 偏移

    # ── 1. 品牌头部 ──────────────────────────────────────
    y += 32
    parts.append(
        f'<text x="{W // 2}" y="{y}" text-anchor="middle" '
        f'font-family="\'JetBrains Mono\', monospace" font-weight="700" '
        f'font-size="16" letter-spacing="3" fill="{_ACCENT}">OPENNEWS</text>'
    )
    y += 18
    parts.append(
        f'<text x="{W // 2}" y="{y}" text-anchor="middle" '
        f'font-family="\'JetBrains Mono\', monospace" font-weight="400" '
        f'font-size="10" letter-spacing="2" fill="{_TEXT_DIM}">'
        f'{"新闻影响快照" if is_zh else "IMPACT SNAPSHOT"}</text>'
    )
    y += 16
    gen_at = data.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(gen_at)
        gen_text = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        gen_text = gen_at[:19]
    parts.append(
        f'<text x="{W // 2}" y="{y}" text-anchor="middle" '
        f'font-family="\'JetBrains Mono\', monospace" font-size="9" fill="{_TEXT_DIM}">'
        f'{_esc(gen_text)}</text>'
    )

    # 分隔线
    y += 12
    parts.append(
        f'<line x1="{PAD}" y1="{y}" x2="{W - PAD}" y2="{y}" '
        f'stroke="{_BORDER}" stroke-width="1"/>'
    )

    # ── 2. 筛选摘要 ──────────────────────────────────────
    y += 22
    scope = data.get("scope_text", "")
    score_range = data.get("score_range", "0–100")
    summary = f"{scope}  |  {'评分' if is_zh else 'Score'} {score_range}"
    parts.append(
        f'<text x="{W // 2}" y="{y}" text-anchor="middle" '
        f'font-family="\'Noto Sans SC\', sans-serif" font-size="12" fill="{_TEXT}">'
        f'{_esc(summary)}</text>'
    )

    # ── 3. 核心指标 (2x2) ────────────────────────────────
    y += 24
    metrics = [
        (
            str(data.get("filtered_count", 0)),
            "筛选命中" if is_zh else "Filtered",
        ),
        (
            f'{data.get("filtered_ratio", 0):.1f}%',
            "占比" if is_zh else "Ratio",
        ),
        (
            str(data.get("above75", 0)),
            "高影响(75+)" if is_zh else "High(75+)",
        ),
        (
            str(data.get("total_items", 0)),
            "总新闻数" if is_zh else "Total",
        ),
    ]
    box_w = (W - PAD * 2 - 12) // 2
    box_h = 52
    for i, (val, label) in enumerate(metrics):
        col = i % 2
        row = i // 2
        bx = PAD + col * (box_w + 12)
        by = y + row * (box_h + 8)
        parts.append(
            f'<rect x="{bx}" y="{by}" width="{box_w}" height="{box_h}" '
            f'rx="6" fill="{_CARD_BG}" stroke="{_BORDER}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{bx + box_w // 2}" y="{by + 24}" text-anchor="middle" '
            f'font-family="\'JetBrains Mono\', monospace" font-weight="700" '
            f'font-size="18" fill="{_TEXT_BRIGHT}">{_esc(val)}</text>'
        )
        parts.append(
            f'<text x="{bx + box_w // 2}" y="{by + 42}" text-anchor="middle" '
            f'font-family="\'Noto Sans SC\', sans-serif" font-size="10" fill="{_TEXT_DIM}">'
            f'{_esc(label)}</text>'
        )
    y += box_h * 2 + 8 + 16

    # ── 4. 环形图 + 堆叠条 ───────────────────────────────
    # 环形图：筛选占比
    cx = W // 2 - 60
    cy = y + 45
    r = 36
    stroke_w = 10
    total = data.get("total_items", 0) or 1
    filtered = data.get("filtered_count", 0)
    ratio_val = filtered / total
    circumference = 2 * 3.14159 * r
    dash = ratio_val * circumference
    gap = circumference - dash

    # 背景圆
    parts.append(
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{_BORDER}" stroke-width="{stroke_w}"/>'
    )
    # 前景弧
    parts.append(
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{_ACCENT}" stroke-width="{stroke_w}" '
        f'stroke-dasharray="{dash:.1f} {gap:.1f}" '
        f'stroke-dashoffset="{circumference * 0.25:.1f}" '
        f'stroke-linecap="round"/>'
    )
    # 中心文字
    parts.append(
        f'<text x="{cx}" y="{cy + 1}" text-anchor="middle" dominant-baseline="middle" '
        f'font-family="\'JetBrains Mono\', monospace" font-weight="700" '
        f'font-size="14" fill="{_TEXT_BRIGHT}">{data.get("filtered_ratio", 0):.1f}%</text>'
    )
    parts.append(
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" '
        f'font-family="\'Noto Sans SC\', sans-serif" font-size="8" fill="{_TEXT_DIM}">'
        f'{"筛选占比" if is_zh else "filtered"}</text>'
    )

    # 堆叠条：高/中/低
    bar_x = W // 2 + 10
    bar_w = W - PAD - bar_x
    bar_h = 14
    fl = data.get("filtered_levels", {"高": 0, "中": 0, "低": 0})
    fl_total = sum(fl.values()) or 1
    bar_y_start = cy - 30

    for idx, (lv, color, bg_color) in enumerate([
        ("高", _HIGH, _HIGH_BG),
        ("中", _MID, _MID_BG),
        ("低", _LOW, _LOW_BG),
    ]):
        by = bar_y_start + idx * (bar_h + 10)
        count = fl.get(lv, 0)
        pct = count / fl_total
        fill_w = max(2, pct * bar_w)

        lv_label = lv if is_zh else {"高": "High", "中": "Mid", "低": "Low"}[lv]
        parts.append(
            f'<text x="{bar_x}" y="{by - 2}" '
            f'font-family="\'JetBrains Mono\', monospace" font-size="9" fill="{color}">'
            f'{_esc(lv_label)} {count}</text>'
        )
        parts.append(
            f'<rect x="{bar_x}" y="{by}" width="{bar_w}" height="{bar_h}" '
            f'rx="3" fill="{bg_color}"/>'
        )
        parts.append(
            f'<rect x="{bar_x}" y="{by}" width="{fill_w:.1f}" height="{bar_h}" '
            f'rx="3" fill="{color}" opacity="0.7"/>'
        )

    y = cy + 55

    # 分隔线
    y += 4
    parts.append(
        f'<line x1="{PAD}" y1="{y}" x2="{W - PAD}" y2="{y}" '
        f'stroke="{_BORDER}" stroke-width="1"/>'
    )

    # ── 5. 新闻列表 ──────────────────────────────────────
    top_news = data.get("top_news", [])
    if top_news:
        y += 18
        parts.append(
            f'<text x="{PAD}" y="{y}" '
            f'font-family="\'Noto Sans SC\', sans-serif" font-weight="600" '
            f'font-size="11" fill="{_TEXT_BRIGHT}">'
            f'{"热门新闻" if is_zh else "Top News"}</text>'
        )
        y += 8

        for item in top_news:
            y += 18
            score = item.get("score", 0)
            level = item.get("level", "低")
            title = _truncate(item.get("title", ""), 28)
            source = _source_name(item.get("source", ""))
            time_str = _fmt_time(item.get("published_at", ""))
            sc_color = _level_color(level)

            # 分数
            parts.append(
                f'<text x="{PAD}" y="{y}" '
                f'font-family="\'JetBrains Mono\', monospace" font-weight="700" '
                f'font-size="13" fill="{sc_color}">{score:.1f}</text>'
            )
            # 标题
            parts.append(
                f'<text x="{PAD + 44}" y="{y}" '
                f'font-family="\'Noto Sans SC\', sans-serif" font-size="11" fill="{_TEXT}">'
                f'{_esc(title)}</text>'
            )
            # 来源 + 时间
            y += 14
            parts.append(
                f'<text x="{PAD + 44}" y="{y}" '
                f'font-family="\'JetBrains Mono\', monospace" font-size="9" fill="{_TEXT_DIM}">'
                f'{_esc(source)}  {_esc(time_str)}</text>'
            )
            y += 4

    # ── 6. 页脚 ──────────────────────────────────────────
    y += 20
    parts.append(
        f'<line x1="{PAD}" y1="{y}" x2="{W - PAD}" y2="{y}" '
        f'stroke="{_BORDER}" stroke-width="1"/>'
    )
    y += 16
    footer = "基于当前筛选条件生成" if is_zh else "Based on current filters"
    parts.append(
        f'<text x="{W // 2}" y="{y}" text-anchor="middle" '
        f'font-family="\'Noto Sans SC\', sans-serif" font-size="9" fill="{_TEXT_DIM}">'
        f'{_esc(footer)}</text>'
    )
    y += 14
    parts.append(
        f'<text x="{W // 2}" y="{y}" text-anchor="middle" '
        f'font-family="\'JetBrains Mono\', monospace" font-weight="600" '
        f'font-size="9" letter-spacing="2" fill="{_ACCENT}">OPENNEWS</text>'
    )
    y += 20  # 底部留白

    # ── 组装 SVG ─────────────────────────────────────────
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{W}" height="{y}" viewBox="0 0 {W} {y}">\n'
        f'  <rect width="{W}" height="{y}" rx="12" fill="{_BG}"/>\n'
        f'  <rect x="8" y="8" width="{W - 16}" height="{y - 16}" rx="10" '
        f'fill="{_CARD_BG}" stroke="{_BORDER}" stroke-width="1"/>\n'
    )
    for p in parts:
        svg += f"  {p}\n"
    svg += "</svg>"
    return svg
