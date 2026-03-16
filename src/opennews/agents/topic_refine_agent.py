"""Topic Refine Agent — 使用 LLM 对聚类结果进行主题精炼。

解决纯 embedding 相似度聚类的误聚合问题：
将候选组内的新闻发给 LLM，让其判断哪些真正属于同一主题，
并拆分不相关的新闻为独立子组。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from opennews.llm.client import LLMClient, LLMConfig
from opennews.topic.online_topic_model import TopicAssignment

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RefinedGroup:
    """LLM 精炼后的一个主题子组。"""
    label_zh: str
    label_en: str
    member_indices: list[int]  # 在原始候选组中的索引

    @property
    def label_dict(self) -> dict[str, str]:
        return {"zh": self.label_zh, "en": self.label_en}


class TopicRefineAgent:
    """调用 LLM 对聚类候选组进行精细化拆分。"""

    # 单次 LLM 调用的最大标题数，超过则分批
    _MAX_BATCH_SIZE = 20

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.load()
        self._client = LLMClient(self.config)

    def refine_topics(
        self,
        docs: list[str],
        assignments: list[TopicAssignment],
        labels: dict[int, dict[str, str]],
    ) -> tuple[list[TopicAssignment], dict[int, dict[str, str]]]:
        """对聚类结果进行 LLM 精炼。

        Args:
            docs: 新闻文档列表（title\\ncontent）
            assignments: 原始聚类分配
            labels: 原始 topic_id → {"zh": "...", "en": "..."} 映射

        Returns:
            (refined_assignments, refined_labels) 精炼后的分配和双语标签
        """
        if not self.config.topic_refine_enabled:
            logger.info("topic refine disabled, skipping")
            return assignments, labels

        if not self.config.api_key:
            logger.warning("LLM api_key not configured, skipping topic refine")
            return assignments, labels

        # 按 topic_id 分组（只处理 ≥0 的聚合主题，solo 不需要精炼）
        groups: dict[int, list[int]] = {}
        for i, a in enumerate(assignments):
            if a.topic_id >= 0:
                groups.setdefault(a.topic_id, []).append(i)

        if not groups:
            return assignments, labels

        # 构建新的分配结果
        new_assignments = list(assignments)  # 浅拷贝
        new_labels = dict(labels)
        next_topic_id = max((a.topic_id for a in assignments), default=-1) + 1
        next_solo_id = min((a.topic_id for a in assignments), default=0)
        if next_solo_id >= 0:
            next_solo_id = -1

        for tid, member_indices in groups.items():
            if len(member_indices) <= 1:
                continue  # 单条无需精炼

            titles = [docs[i].split("\n")[0] for i in member_indices]

            # 对过大的组分批调用 LLM，每批独立精炼
            if len(titles) > self._MAX_BATCH_SIZE:
                logger.info(
                    "topic %d has %d items, splitting into batches of %d for LLM refine",
                    tid, len(titles), self._MAX_BATCH_SIZE,
                )
                all_refined: list[RefinedGroup] = []
                for batch_start in range(0, len(titles), self._MAX_BATCH_SIZE):
                    batch_titles = titles[batch_start:batch_start + self._MAX_BATCH_SIZE]
                    batch_refined = self._call_llm_with_retry(tid, batch_titles)
                    if batch_refined is None:
                        # 该批次失败，保持原始索引不变
                        for local_i in range(len(batch_titles)):
                            all_refined.append(RefinedGroup(
                                label_zh="未分类", label_en="Uncategorized",
                                member_indices=[batch_start + local_i],
                            ))
                    else:
                        # 将批次内的局部索引偏移到组内全局索引
                        for rg in batch_refined:
                            shifted = [batch_start + idx for idx in rg.member_indices]
                            all_refined.append(RefinedGroup(
                                label_zh=rg.label_zh, label_en=rg.label_en,
                                member_indices=shifted,
                            ))
                refined = all_refined
            else:
                refined = self._call_llm_with_retry(tid, titles)

            if refined is None:
                continue

            if not refined or (len(refined) == 1 and
                    sorted(refined[0].member_indices) == list(range(len(titles)))):
                # LLM 认为全部属于同一主题，保持不变
                continue

            logger.info("topic %d split into %d sub-groups by LLM", tid, len(refined))

            # 第一个子组继承原 topic_id
            first = True
            for rg in refined:
                if not rg.member_indices:
                    continue

                if first:
                    # 继承原 topic_id，更新 label
                    use_tid = tid
                    new_labels[use_tid] = rg.label_dict
                    first = False
                elif len(rg.member_indices) == 1:
                    # 单条新闻 → solo
                    use_tid = next_solo_id
                    new_labels[use_tid] = rg.label_dict
                    next_solo_id -= 1
                else:
                    # 新的聚合主题
                    use_tid = next_topic_id
                    new_labels[use_tid] = rg.label_dict
                    next_topic_id += 1

                for local_idx in rg.member_indices:
                    if local_idx < len(member_indices):
                        global_idx = member_indices[local_idx]
                        new_assignments[global_idx] = TopicAssignment(
                            topic_id=use_tid,
                            probability=assignments[global_idx].probability,
                        )

        clustered = sum(1 for a in new_assignments if a.topic_id >= 0)
        logger.info("after LLM refine: %d clustered, %d solo",
                     clustered, len(new_assignments) - clustered)

        # ── 批量翻译未生成双语标签的主题 ──────────────
        # 聚类阶段和 LLM 失败时 label 的 zh/en 相同（都是原标题），需要补翻译
        new_labels = self._translate_missing_labels(new_labels)

        # ── 兜底：LLM 翻译也失败时，用规则区分中英文 ──────
        new_labels = self._fallback_bilingual(new_labels)

        return new_assignments, new_labels

    # ── 重试未翻译标签 ────────────────────────────────────

    def retry_failed_labels(
        self, failed: list[tuple[int, dict[str, str]]],
    ) -> list[tuple[int, dict[str, str]]]:
        """对带 [EN]/[ZH] 前缀的标签重新调用 LLM 翻译。

        Args:
            failed: [(record_id, {"zh": "...", "en": "..."}), ...]

        Returns:
            成功翻译的 [(record_id, {"zh": "...", "en": "..."}), ...]
        """
        if not self.config.api_key or not failed:
            return []

        # 还原原始文本：去掉 [EN]/[ZH] 前缀，使 zh==en 以触发翻译逻辑
        restore_map: dict[int, tuple[int, str]] = {}  # fake_tid → (record_id, original_text)
        labels: dict[int, dict[str, str]] = {}
        for i, (record_id, lbl) in enumerate(failed):
            zh, en = lbl.get("zh", ""), lbl.get("en", "")
            if zh.startswith("[EN] "):
                original = en  # en 是原始英文
            elif en.startswith("[ZH] "):
                original = zh  # zh 是原始中文
            else:
                continue
            fake_tid = -(10000 + i)
            restore_map[fake_tid] = (record_id, original)
            labels[fake_tid] = {"zh": original, "en": original}

        if not labels:
            return []

        logger.info("retrying translation for %d failed topic labels", len(labels))
        translated = self._translate_missing_labels(labels)

        results: list[tuple[int, dict[str, str]]] = []
        for fake_tid, new_lbl in translated.items():
            zh, en = new_lbl.get("zh", ""), new_lbl.get("en", "")
            # 只保留真正翻译成功的（zh != en 且无前缀）
            if zh and en and zh != en and not zh.startswith("[EN]") and not en.startswith("[ZH]"):
                record_id, _ = restore_map[fake_tid]
                results.append((record_id, new_lbl))

        logger.info("successfully re-translated %d/%d labels", len(results), len(labels))
        return results

    # ── 本地规则兜底 ──────────────────────────────────────

    @staticmethod
    def _is_mostly_chinese(text: str) -> bool:
        """判断文本是否以中文字符为主。"""
        if not text:
            return False
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        return cjk / max(len(text.replace(" ", "")), 1) > 0.3

    @staticmethod
    def _fallback_bilingual(
        labels: dict[int, dict[str, str]],
    ) -> dict[int, dict[str, str]]:
        """LLM 翻译全部失败时的本地兜底：根据文本语种将另一语言设为带标记的占位。

        如果原标题是中文，en 设为 "[ZH] 原标题"；
        如果原标题是英文，zh 设为 "[EN] 原标题"。
        这样前端至少能区分哪个是原始语言、哪个是占位。
        """
        result = dict(labels)
        for tid, lbl in result.items():
            zh, en = lbl.get("zh", ""), lbl.get("en", "")
            if zh != en or not zh:
                continue  # 已经不同，跳过
            if TopicRefineAgent._is_mostly_chinese(zh):
                result[tid] = {"zh": zh, "en": f"[ZH] {zh}"}
            else:
                result[tid] = {"zh": f"[EN] {en}", "en": en}
        return result

    # ── 批量翻译 ──────────────────────────────────────────

    _TRANSLATE_BATCH_SIZE = 40  # 单次翻译请求的最大条目数

    def _translate_missing_labels(
        self, labels: dict[int, dict[str, str]],
    ) -> dict[int, dict[str, str]]:
        """对 zh == en 的 label 批量调用 LLM 生成缺失的另一语言标签。"""
        if not self.config.api_key:
            return labels

        # 收集需要翻译的 topic_id 和对应标题
        to_translate: list[tuple[int, str]] = []
        for tid, lbl in labels.items():
            if lbl.get("zh") == lbl.get("en") and lbl.get("zh"):
                to_translate.append((tid, lbl["zh"]))

        if not to_translate:
            return labels

        logger.info("translating %d topic labels to bilingual", len(to_translate))
        result = dict(labels)

        for batch_start in range(0, len(to_translate), self._TRANSLATE_BATCH_SIZE):
            batch = to_translate[batch_start:batch_start + self._TRANSLATE_BATCH_SIZE]
            translated = self._call_translate_batch(batch)
            if translated:
                for (tid, _orig), pair in zip(batch, translated):
                    if pair is not None:
                        result[tid] = {"zh": pair[0], "en": pair[1]}

        return result

    def _call_translate_batch(
        self, items: list[tuple[int, str]],
    ) -> list[tuple[str, str]] | None:
        """批量翻译标题，返回 [(zh, en), ...] 或 None。"""
        numbered = "\n".join(f"[{i}] {title}" for i, (_, title) in enumerate(items))

        system = (
            "你是一个多语言新闻标题翻译专家。"
            "你需要为每条新闻标题同时提供简洁的中文主题标签和英文主题标签。"
            "如果原标题是中文，生成对应的英文标签；如果原标题是英文，生成对应的中文标签。"
            "标签应概括新闻核心内容，10~20字（中文）或 5~10 words（英文）。"
        )
        user = (
            f"为以下新闻标题生成双语主题标签：\n\n{numbered}\n\n"
            '输出严格 JSON 数组：\n'
            '[{"zh": "中文标签", "en": "English label"}]\n\n'
            "要求：\n"
            "1. 数组长度与输入条目数一致，顺序对应\n"
            "2. 只输出 JSON 数组"
        )

        try:
            raw = self._client.chat(system, user)
        except Exception as e:
            logger.warning("translate batch failed: %s", e)
            return None

        return self._parse_translate_response(raw, len(items))

    @staticmethod
    def _parse_translate_response(raw: str, expected: int) -> list[tuple[str, str]] | None:
        """解析翻译 LLM 返回的 JSON 数组。"""
        json_match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        text = json_match.group(1).strip() if json_match else raw.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
            if bracket_match:
                try:
                    data = json.loads(bracket_match.group())
                except json.JSONDecodeError:
                    logger.warning("failed to parse translate response: %s", text[:200])
                    return None
            else:
                logger.warning("no JSON array in translate response: %s", text[:200])
                return None

        if not isinstance(data, list):
            return None

        result = []
        for item in data[:expected]:
            if isinstance(item, dict):
                zh = item.get("zh", "")
                en = item.get("en", "")
                if zh and en:
                    result.append((zh, en))
                else:
                    result.append(None)
            else:
                result.append(None)

        # 补齐不足的部分
        while len(result) < expected:
            result.append(None)

        return result

    def _call_llm_with_retry(self, tid: int, titles: list[str]) -> list[RefinedGroup] | None:
        """带重试的 LLM 精炼调用，失败返回 None。"""
        max_retries = max(0, self.config.topic_refine_max_retries)
        last_err: Exception | None = None

        for attempt in range(1 + max_retries):
            try:
                return self._call_llm_refine(titles)
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM refine failed for topic %d (attempt %d/%d): %s — retrying in %ds",
                        tid, attempt + 1, 1 + max_retries, e, wait,
                    )
                    time.sleep(wait)

        logger.warning(
            "LLM refine failed for topic %d after %d attempts (%d items), "
            "keeping original clustering. "
            "Check LLM API connectivity and config/llm.yaml settings. "
            "Last error: %s",
            tid, 1 + max_retries, len(titles), last_err,
        )
        return None

    def _call_llm_refine(self, titles: list[str]) -> list[RefinedGroup]:
        """调用 LLM 对一组新闻标题进行主题拆分。"""
        news_list = "\n".join(f"[{i}] {t}" for i, t in enumerate(titles))

        system = self.config.topic_refine_system_prompt
        user_template = self.config.topic_refine_user_prompt_template

        if not system or not user_template:
            # 使用内置默认 prompt
            system = (
                "你是一个新闻主题聚类分析师。"
                "你擅长从一组新闻标题中识别出哪些报道的是同一件事或同一个话题，哪些只是表面相似但实际无关。"
                "判断标准是新闻所讨论的核心事件、主体和因果关系，而非共享的宽泛关键词或领域。"
            )
            user_template = (
                "以下新闻被初步判定为同一主题，请重新审视并分组：\n\n{news_list}\n\n"
                "将真正讨论同一事件/话题的新闻归为一组，不相关的拆分出去。\n\n"
                '输出严格 JSON：\n'
                '{{"groups": [{{"label_zh": "概括的中文主题标签，10~20字适宜", "label_en": "Concise English topic label, 5-10 words", "indices": [0, 2]}}]}}\n\n'
                "要求：\n"
                "1. indices 为新闻序号（从 0 开始），每条新闻只能出现一次\n"
                "2. 与组内其他新闻无关的，单独成组\n"
                "3. label_zh 应准确概括该组的共同话题（中文），label_en 为对应的英文主题标签\n"
                "4. 只输出 JSON"
            )

        user = user_template.replace("{news_list}", news_list)
        raw = self._client.chat(system, user)
        return self._parse_response(raw, len(titles))

    @staticmethod
    def _parse_response(raw: str, n_titles: int) -> list[RefinedGroup]:
        """解析 LLM 返回的 JSON，容错处理。"""
        # 提取 JSON 块（兼容 markdown code block）
        json_match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        text = json_match.group(1).strip() if json_match else raw.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试修复常见问题：提取第一个 { ... }
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                try:
                    data = json.loads(brace_match.group())
                except json.JSONDecodeError:
                    logger.warning("failed to parse LLM response as JSON: %s", text[:200])
                    return []
            else:
                logger.warning("no JSON found in LLM response: %s", text[:200])
                return []

        groups_raw = data.get("groups", [])
        if not isinstance(groups_raw, list):
            return []

        seen = set()
        result = []
        for g in groups_raw:
            label_zh = g.get("label_zh") or g.get("label", "未知主题")
            label_en = g.get("label_en", label_zh)
            indices = g.get("indices", [])
            # 过滤无效索引和重复
            valid = [i for i in indices if isinstance(i, int) and 0 <= i < n_titles and i not in seen]
            seen.update(valid)
            if valid:
                result.append(RefinedGroup(label_zh=label_zh, label_en=label_en, member_indices=valid))

        # 补全遗漏的新闻（LLM 可能漏掉某些）
        missing = [i for i in range(n_titles) if i not in seen]
        for i in missing:
            result.append(RefinedGroup(label_zh="未分类", label_en="Uncategorized", member_indices=[i]))

        return result
