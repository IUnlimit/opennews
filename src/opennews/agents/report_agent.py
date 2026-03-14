"""ReportAgent — DK-CoT 多维度评分 + Markdown 报告生成。

论文依据：
  - DK-CoT（Domain-Knowledge Chain-of-Thought）多链推理
  - LLM-Assisted News Discovery 评分体系
  - FinSCRA 模糊逻辑融合

四维评分（0-100）：
  股价相关性 (40%) — 基于 price_signal + market_impact 特征
  市场情绪   (20%) — 基于分类置信度 + controversy 特征
  政策风险   (20%) — 基于 regulatory_risk 特征 + 分类结果
  传播广度   (20%) — 基于实体数量 + 跨源覆盖 + 社区数

最终得分持久化到 Neo4j News 节点，支持按得分筛选。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass(slots=True)
class DKCoTScores:
    """DK-CoT 四维评分明细。"""
    stock_relevance: float     # 股价相关性 0-100
    market_sentiment: float    # 市场情绪 0-100
    policy_risk: float         # 政策风险 0-100
    spread_breadth: float      # 传播广度 0-100

    def to_dict(self) -> dict[str, float]:
        return {
            "stock_relevance": self.stock_relevance,
            "market_sentiment": self.market_sentiment,
            "policy_risk": self.policy_risk,
            "spread_breadth": self.spread_breadth,
        }


@dataclass(slots=True)
class NewsReport:
    """单条新闻的影响评估报告。"""
    news_id: str
    final_score: float         # 最终影响得分 0-100
    impact_level: str          # "高" / "中" / "低"
    dk_cot_scores: DKCoTScores
    reasoning: str             # DK-CoT 推理链文本
    markdown: str              # 完整 Markdown 报告
    viz_suggestions: list[str] # 可视化建议

    def to_dict(self) -> dict:
        return {
            "news_id": self.news_id,
            "final_score": self.final_score,
            "impact_level": self.impact_level,
            "dk_cot_scores": self.dk_cot_scores.to_dict(),
            "reasoning": self.reasoning,
            "markdown": self.markdown,
            "viz_suggestions": self.viz_suggestions,
        }


# ── 评分引擎 ──────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _feature_to_100(val: float, scale_max: float = 5.0) -> float:
    """将 1-5 分特征映射到 0-100。"""
    return _clamp((val - 1.0) / (scale_max - 1.0) * 100.0)


class ReportAgent:
    """金融影响 ReportAgent。

    Prompt 模板（内化为算法逻辑）：
    ─────────────────────────────────
    你是金融影响 ReportAgent。
    输入：同类新闻 Graph 子图 + 时序记忆
    用 DK-CoT（领域知识链式思考）计算最终影响得分（0-100）：
    维度：股价相关性(40%)、市场情绪(20%)、政策风险(20%)、传播广度(20%)
    输出 Markdown 报告 + 可视化建议（趋势图）。
    ─────────────────────────────────
    """

    def __init__(
        self,
        weight_stock: float = 0.40,
        weight_sentiment: float = 0.20,
        weight_policy: float = 0.20,
        weight_spread: float = 0.20,
    ):
        self.weights = {
            "stock_relevance": weight_stock,
            "market_sentiment": weight_sentiment,
            "policy_risk": weight_policy,
            "spread_breadth": weight_spread,
        }
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning("DK-CoT weights sum to %.2f, normalizing", total)
            self.weights = {k: v / total for k, v in self.weights.items()}

    # ── DK-CoT 链式推理 ──────────────────────────────────────

    def _score_stock_relevance(
        self, features: dict, classification: dict, trend: dict | None
    ) -> tuple[float, str]:
        """维度1：股价相关性 — price_signal + market_impact + 趋势方向。"""
        price_sig = features.get("price_signal", 1.0)
        mkt_impact = features.get("market_impact", 1.0)
        base = (_feature_to_100(price_sig) * 0.6 + _feature_to_100(mkt_impact) * 0.4)

        # 趋势加成：rising +10, falling -5
        if trend:
            direction = trend.get("trend_direction", "stable")
            if direction == "rising":
                base = _clamp(base + 10)
            elif direction == "falling":
                base = _clamp(base - 5)

        reasoning = (
            f"[股价相关性] price_signal={price_sig:.1f}→{_feature_to_100(price_sig):.0f}, "
            f"market_impact={mkt_impact:.1f}→{_feature_to_100(mkt_impact):.0f}, "
            f"trend={'N/A' if not trend else trend.get('trend_direction', 'stable')}, "
            f"score={base:.1f}"
        )
        return round(base, 2), reasoning

    def _score_market_sentiment(
        self, features: dict, classification: dict
    ) -> tuple[float, str]:
        """维度2：市场情绪 — controversy + 分类置信度 + impact 特征。"""
        controversy = features.get("controversy", 1.0)
        impact_feat = features.get("impact", 1.0)
        confidence = classification.get("confidence", 0.0)

        base = (
            _feature_to_100(controversy) * 0.4
            + _feature_to_100(impact_feat) * 0.3
            + confidence * 100 * 0.3
        )

        reasoning = (
            f"[市场情绪] controversy={controversy:.1f}→{_feature_to_100(controversy):.0f}, "
            f"impact={impact_feat:.1f}→{_feature_to_100(impact_feat):.0f}, "
            f"clf_confidence={confidence:.2f}, score={base:.1f}"
        )
        return round(base, 2), reasoning

    def _score_policy_risk(
        self, features: dict, classification: dict
    ) -> tuple[float, str]:
        """维度3：政策风险 — regulatory_risk + 是否 policy_regulation 类别。"""
        reg_risk = features.get("regulatory_risk", 1.0)
        base = _feature_to_100(reg_risk) * 0.7

        category = classification.get("category", "unknown")
        cat_scores = classification.get("all_scores", {})
        policy_prob = cat_scores.get("policy_regulation", 0.0)
        base += policy_prob * 100 * 0.3

        # 如果主类别就是 policy_regulation，额外加成
        if category == "policy_regulation":
            base = _clamp(base + 10)

        reasoning = (
            f"[政策风险] regulatory_risk={reg_risk:.1f}→{_feature_to_100(reg_risk):.0f}, "
            f"policy_prob={policy_prob:.2f}, category={category}, score={base:.1f}"
        )
        return round(base, 2), reasoning

    def _score_spread_breadth(
        self, entities: list[dict], news_source: str, trend: dict | None
    ) -> tuple[float, str]:
        """维度4：传播广度 — 实体数量 + 跨源覆盖 + 社区数。"""
        entity_count = len(entities)
        # 实体数映射：0→0, 5→50, 10+→100
        entity_score = _clamp(entity_count * 10.0)

        # 来源多样性（简单启发式）
        source_score = 50.0  # 基线
        if any(k in news_source for k in ("reuters", "caixin")):
            source_score = 70.0
        if any(k in news_source for k in ("weibo", "sina")):
            source_score = max(source_score, 60.0)

        # 趋势中的新闻总数
        total_count = (trend or {}).get("total_news_count", 0)
        count_score = _clamp(total_count * 5.0)

        base = entity_score * 0.4 + source_score * 0.3 + count_score * 0.3

        reasoning = (
            f"[传播广度] entities={entity_count}→{entity_score:.0f}, "
            f"source_score={source_score:.0f}, "
            f"topic_news_count={total_count}→{count_score:.0f}, score={base:.1f}"
        )
        return round(base, 2), reasoning

    # ── 主评分入口 ────────────────────────────────────────────

    def evaluate(
        self,
        news_id: str,
        title: str,
        features: dict,
        classification: dict,
        entities: list[dict],
        news_source: str,
        trend: dict | None = None,
    ) -> NewsReport:
        """对单条新闻执行 DK-CoT 评分 + 生成报告。"""
        # Chain-of-Thought: 逐维度推理
        s1, r1 = self._score_stock_relevance(features, classification, trend)
        s2, r2 = self._score_market_sentiment(features, classification)
        s3, r3 = self._score_policy_risk(features, classification)
        s4, r4 = self._score_spread_breadth(entities, news_source, trend)

        scores = DKCoTScores(
            stock_relevance=s1,
            market_sentiment=s2,
            policy_risk=s3,
            spread_breadth=s4,
        )

        # 加权融合（FinSCRA 模糊逻辑）
        final = (
            s1 * self.weights["stock_relevance"]
            + s2 * self.weights["market_sentiment"]
            + s3 * self.weights["policy_risk"]
            + s4 * self.weights["spread_breadth"]
        )

        # 领域相关性惩罚：分类置信度低说明不属于任何金融类别，
        # 对最终分数施加折扣，避免非金融新闻被高估
        clf_confidence = classification.get("confidence", 0.0)
        domain_penalty = 1.0
        if clf_confidence < 0.3:
            domain_penalty = 0.5
        elif clf_confidence < 0.4:
            domain_penalty = 0.7

        penalty_reason = ""
        if domain_penalty < 1.0:
            final *= domain_penalty
            penalty_reason = (
                f"\n  [领域惩罚] clf_confidence={clf_confidence:.2f} < 阈值, "
                f"penalty={domain_penalty:.1f}"
            )

        final = round(_clamp(final), 2)

        # 影响等级
        if final > 75:
            level = "高"
        elif final > 40:
            level = "中"
        else:
            level = "低"

        reasoning = f"DK-CoT 推理链:\n  {r1}\n  {r2}\n  {r3}\n  {r4}{penalty_reason}\n  → 加权得分={final}, 等级={level}"

        # 生成 Markdown 报告
        markdown = self._render_markdown(
            title=title,
            news_id=news_id,
            scores=scores,
            final=final,
            level=level,
            reasoning=reasoning,
            classification=classification,
            trend=trend,
        )

        # 可视化建议
        viz = self._suggest_visualizations(scores, trend)

        return NewsReport(
            news_id=news_id,
            final_score=final,
            impact_level=level,
            dk_cot_scores=scores,
            reasoning=reasoning,
            markdown=markdown,
            viz_suggestions=viz,
        )

    def evaluate_batch(
        self,
        payloads: list[dict],
        trends: dict | None = None,
    ) -> list[NewsReport]:
        """批量评估。payloads 中每项需包含 news/features/classification/entities。"""
        reports = []
        for p in payloads:
            news = p.get("news", {})
            topic_id = p.get("topic", {}).get("topic_id", -1)
            trend = None
            if trends and topic_id in trends:
                t = trends[topic_id]
                trend = {
                    "trend_direction": t.trend_direction if hasattr(t, "trend_direction") else t.get("trend_direction", "stable"),
                    "avg_impact": t.avg_impact if hasattr(t, "avg_impact") else t.get("avg_impact", 0.0),
                    "latest_impact": t.latest_impact if hasattr(t, "latest_impact") else t.get("latest_impact", 0.0),
                    "total_news_count": t.total_news_count if hasattr(t, "total_news_count") else t.get("total_news_count", 0),
                }

            report = self.evaluate(
                news_id=news.get("news_id", ""),
                title=news.get("title", ""),
                features=p.get("features") or {},
                classification=p.get("classification") or {},
                entities=p.get("entities", []),
                news_source=news.get("source", ""),
                trend=trend,
            )
            reports.append(report)
        return reports

    # ── Markdown 渲染 ─────────────────────────────────────────

    def _render_markdown(
        self,
        title: str,
        news_id: str,
        scores: DKCoTScores,
        final: float,
        level: str,
        reasoning: str,
        classification: dict,
        trend: dict | None,
    ) -> str:
        trend_dir = (trend or {}).get("trend_direction", "N/A")
        trend_avg = (trend or {}).get("avg_impact", 0.0)
        category = classification.get("category", "unknown")
        confidence = classification.get("confidence", 0.0)

        return f"""## 金融影响评估报告

**新闻**: {title}
**ID**: `{news_id}`
**分类**: {category} (置信度 {confidence:.1%})
**影响等级**: **{level}** (得分 {final:.1f}/100)

### DK-CoT 四维评分

| 维度 | 得分 | 权重 |
|------|------|------|
| 股价相关性 | {scores.stock_relevance:.1f} | {self.weights['stock_relevance']:.0%} |
| 市场情绪 | {scores.market_sentiment:.1f} | {self.weights['market_sentiment']:.0%} |
| 政策风险 | {scores.policy_risk:.1f} | {self.weights['policy_risk']:.0%} |
| 传播广度 | {scores.spread_breadth:.1f} | {self.weights['spread_breadth']:.0%} |
| **加权总分** | **{final:.1f}** | |

### 推理过程

```
{reasoning}
```

### 趋势上下文

- 趋势方向: {trend_dir}
- 窗口平均影响: {trend_avg:.2f}
"""

    # ── 可视化建议 ─────────────────────────────────────────────

    def _suggest_visualizations(
        self, scores: DKCoTScores, trend: dict | None
    ) -> list[str]:
        suggestions = [
            "雷达图: 四维评分对比 (stock_relevance / market_sentiment / policy_risk / spread_breadth)",
        ]
        if trend and trend.get("total_news_count", 0) > 3:
            suggestions.append(
                f"时序折线图: 主题影响趋势 (方向={trend.get('trend_direction', 'stable')}, "
                f"窗口内 {trend.get('total_news_count', 0)} 条新闻)"
            )
        suggestions.append("柱状图: 同主题新闻影响得分分布")
        return suggestions
