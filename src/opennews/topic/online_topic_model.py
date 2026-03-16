from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# 完全链接层次聚类的距离阈值
# 距离 = 1 - cosine_similarity，阈值 0.35 意味着簇内任意两篇相似度 >= 0.65
DISTANCE_THRESHOLD = 0.35

# 至少 2 篇才算聚合主题
MIN_CLUSTER_SIZE = 2

# 单个簇的最大容量，超过则用更严格阈值递归拆分
MAX_CLUSTER_SIZE = 15

# 递归拆分时每次收紧的距离步长
_SPLIT_STEP = 0.05

# 中文 embedding 模型
_CHINESE_EMBED_MODEL = "BAAI/bge-base-zh-v1.5"


def _make_bilingual_label(title: str) -> dict[str, str]:
    """根据标题语种生成初始双语 label。

    中文标题 → zh=标题, en="[ZH] 标题"
    英文标题 → zh="[EN] 标题", en=标题
    """
    cjk = sum(1 for c in title if '\u4e00' <= c <= '\u9fff')
    is_zh = cjk / max(len(title.replace(" ", "")), 1) > 0.3
    if is_zh:
        return {"zh": title, "en": f"[ZH] {title}"}
    else:
        return {"zh": f"[EN] {title}", "en": title}


@dataclass(slots=True)
class TopicAssignment:
    topic_id: int
    probability: float


class OnlineTopicModel:
    def __init__(self, embedding_model=None):
        self._embedder = None
        self._labels: dict[int, dict[str, str]] = {}  # {topic_id: {"zh": "...", "en": "..."}}

    def _get_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(_CHINESE_EMBED_MODEL)
            logger.info("loaded topic embedding model: %s", _CHINESE_EMBED_MODEL)
        return self._embedder

    def update_and_assign(
        self,
        docs: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> list[TopicAssignment]:
        if not docs:
            return []

        self._labels.clear()
        n = len(docs)

        # 只有当外部传入的 embeddings 维度与本模型一致时才复用，
        # 否则用自己的 embedder 重新编码（避免不同模型 embedding 空间混用）
        if embeddings is not None:
            emb_arr = np.array(embeddings) if not isinstance(embeddings, np.ndarray) else embeddings
            expected_dim = self._get_embedder().get_sentence_embedding_dimension()
            if emb_arr.ndim == 2 and emb_arr.shape[1] == expected_dim:
                emb = emb_arr
                logger.debug("reusing external embeddings (dim=%d)", expected_dim)
            else:
                logger.info(
                    "external embeddings dim %s != topic model dim %d, re-encoding",
                    emb_arr.shape[1] if emb_arr.ndim == 2 else "?", expected_dim,
                )
                emb = self._get_embedder().encode(docs, show_progress_bar=False)
        else:
            emb = self._get_embedder().encode(docs, show_progress_bar=False)
        sim = cosine_similarity(emb)

        # 单篇直接独立
        if n == 1:
            return self._assign_all_solo(docs)

        # ── 层次聚类（complete linkage）──────────────
        # complete linkage 保证簇内任意两点距离 <= 阈值
        dist = 1.0 - sim
        np.fill_diagonal(dist, 0.0)
        dist = np.clip(dist, 0, None)  # 避免浮点误差导致负值
        condensed = squareform(dist, checks=False)
        Z = linkage(condensed, method="complete")
        labels = fcluster(Z, t=DISTANCE_THRESHOLD, criterion="distance")

        # ── 统计每个簇 ───────────────────────────────
        from collections import Counter
        cluster_counts = Counter(labels)

        # ── 拆分过大的簇 ──────────────────────────────
        # 对超过 MAX_CLUSTER_SIZE 的簇，用更严格阈值递归二次聚类
        final_clusters: list[list[int]] = []  # 每个元素是该簇包含的全局文档索引列表
        processed_scipy_labels: set[int] = set()

        for scipy_label, count in cluster_counts.items():
            if scipy_label in processed_scipy_labels:
                continue
            processed_scipy_labels.add(scipy_label)
            members = [j for j in range(n) if labels[j] == scipy_label]

            if count < MIN_CLUSTER_SIZE:
                # 独立新闻，不加入 final_clusters，后面单独处理
                continue

            if count <= MAX_CLUSTER_SIZE:
                final_clusters.append(members)
            else:
                # 递归拆分
                sub_clusters = self._split_large_cluster(members, dist, DISTANCE_THRESHOLD)
                final_clusters.extend(sub_clusters)

        # ── 分配 topic_id ─────────────────────────────
        assignments: list[TopicAssignment] = [None] * n  # type: ignore
        cluster_id = 0
        solo_id = -1
        assigned: set[int] = set()

        for members in final_clusters:
            if len(members) < MIN_CLUSTER_SIZE:
                # 拆分后不足 2 篇的降为 solo
                for j in members:
                    title = docs[j].split("\n")[0]
                    self._labels[solo_id] = _make_bilingual_label(title)
                    assignments[j] = TopicAssignment(topic_id=solo_id, probability=0.0)
                    assigned.add(j)
                    solo_id -= 1
                continue

            best = max(members, key=lambda m: np.mean([sim[m][k] for k in members if k != m]))
            title = docs[best].split("\n")[0]
            self._labels[cluster_id] = _make_bilingual_label(title)

            for j in members:
                avg_sim = float(np.mean([sim[j][k] for k in members if k != j]))
                assignments[j] = TopicAssignment(topic_id=cluster_id, probability=avg_sim)
                assigned.add(j)

            cluster_id += 1

        # 处理原始聚类中的独立新闻（count < MIN_CLUSTER_SIZE）
        for i in range(n):
            if i not in assigned:
                title = docs[i].split("\n")[0]
                self._labels[solo_id] = _make_bilingual_label(title)
                assignments[i] = TopicAssignment(topic_id=solo_id, probability=0.0)
                solo_id -= 1

        clustered = sum(1 for a in assignments if a.topic_id >= 0)
        logger.info(
            "topic assignment: %d clustered in %d topics, %d solo",
            clustered, cluster_id, len(assignments) - clustered,
        )
        return assignments

    @staticmethod
    def _split_large_cluster(
        members: list[int],
        full_dist: np.ndarray,
        current_threshold: float,
    ) -> list[list[int]]:
        """递归拆分超过 MAX_CLUSTER_SIZE 的簇。

        每次收紧距离阈值 _SPLIT_STEP，直到所有子簇 <= MAX_CLUSTER_SIZE
        或阈值降到 0.05 以下（兜底停止）。
        """
        if len(members) <= MAX_CLUSTER_SIZE:
            return [members]

        new_threshold = current_threshold - _SPLIT_STEP
        if new_threshold < 0.05:
            # 阈值已经很严格了，强制接受当前簇
            logger.warning(
                "cluster of %d items cannot be split further (threshold=%.2f), keeping as-is",
                len(members), current_threshold,
            )
            return [members]

        # 提取子距离矩阵
        idx = np.array(members)
        sub_dist = full_dist[np.ix_(idx, idx)]
        np.fill_diagonal(sub_dist, 0.0)
        sub_dist = np.clip(sub_dist, 0, None)

        condensed = squareform(sub_dist, checks=False)
        Z = linkage(condensed, method="complete")
        sub_labels = fcluster(Z, t=new_threshold, criterion="distance")

        from collections import Counter
        sub_counts = Counter(sub_labels)

        result: list[list[int]] = []
        seen_labels: set[int] = set()
        for local_i, sl in enumerate(sub_labels):
            if sl in seen_labels:
                continue
            seen_labels.add(sl)
            sub_members = [members[j] for j in range(len(members)) if sub_labels[j] == sl]

            if len(sub_members) > MAX_CLUSTER_SIZE:
                # 仍然过大，继续递归
                result.extend(
                    OnlineTopicModel._split_large_cluster(sub_members, full_dist, new_threshold)
                )
            else:
                result.append(sub_members)

        logger.info(
            "split cluster of %d into %d sub-clusters (threshold %.2f → %.2f)",
            len(members), len(result), current_threshold, new_threshold,
        )
        return result

    def _assign_all_solo(self, docs: list[str]) -> list[TopicAssignment]:
        assignments = []
        for i, doc in enumerate(docs):
            solo_id = -(i + 1)
            title = doc.split("\n")[0]
            self._labels[solo_id] = _make_bilingual_label(title)
            assignments.append(TopicAssignment(topic_id=solo_id, probability=0.0))
        return assignments

    def get_topic_label(self, topic_id: int) -> dict[str, str]:
        """返回 {"zh": "...", "en": "..."} 双语标签。"""
        fallback = f"topic_{topic_id}"
        label = self._labels.get(topic_id)
        if label is None:
            return {"zh": fallback, "en": fallback}
        # 兼容旧的 str 格式
        if isinstance(label, str):
            return {"zh": label, "en": label}
        return label
