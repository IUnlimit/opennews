<template>
  <div ref="rootRef" class="share-card">
    <!-- 1. 品牌头部 -->
    <div class="sc-brand">
      <div class="sc-logo">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="4" width="18" height="16" rx="2" stroke="#2563eb" stroke-width="1.8"/>
          <path d="M7 8H17" stroke="#2563eb" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M7 12H17" stroke="#2563eb" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M7 16H13" stroke="#2563eb" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="1.4" fill="#2563eb"/>
        </svg>
        <span class="sc-logo-text">OPENNEWS</span>
      </div>
      <div class="sc-subtitle">{{ isZh ? '新闻影响快照' : 'IMPACT SNAPSHOT' }}</div>
      <div class="sc-time">{{ generatedTime }}</div>
    </div>

    <div class="sc-divider"></div>

    <!-- 2. 筛选摘要 -->
    <div class="sc-summary">
      {{ data.scopeText }}  |  {{ isZh ? '评分' : 'Score' }} {{ data.scoreRange }}
    </div>

    <!-- 3. 核心指标 1x4 单行 -->
    <div class="sc-metrics">
      <div class="sc-metric-box">
        <div class="sc-metric-val">{{ data.filteredCount }}</div>
        <div class="sc-metric-label">{{ isZh ? '命中' : 'Filtered' }}</div>
      </div>
      <div class="sc-metric-box">
        <div class="sc-metric-val">{{ data.filteredRatio.toFixed(1) }}%</div>
        <div class="sc-metric-label">{{ isZh ? '占比' : 'Ratio' }}</div>
      </div>
      <div class="sc-metric-box">
        <div class="sc-metric-val">{{ data.above75 }}</div>
        <div class="sc-metric-label">{{ isZh ? '高影响' : 'High' }}</div>
      </div>
      <div class="sc-metric-box">
        <div class="sc-metric-val">{{ data.totalItems }}</div>
        <div class="sc-metric-label">{{ isZh ? '总数' : 'Total' }}</div>
      </div>
    </div>

    <!-- 4. 图表区：环图 + 堆叠条（紧凑布局） -->
    <div class="sc-chart-area">
      <!-- 环形图 -->
      <div class="sc-donut-wrap">
        <svg width="76" height="76" viewBox="0 0 76 76">
          <circle cx="38" cy="38" r="28" fill="none" stroke="#dde1e8" stroke-width="8"/>
          <circle cx="38" cy="38" r="28" fill="none" stroke="#2563eb" stroke-width="8"
            :stroke-dasharray="dashArray" :stroke-dashoffset="dashOffset"
            stroke-linecap="round"/>
          <text x="38" y="36" text-anchor="middle" dominant-baseline="middle"
            font-family="'JetBrains Mono', monospace" font-weight="700" font-size="12" fill="#111827">
            {{ data.filteredRatio.toFixed(1) }}%
          </text>
          <text x="38" y="49" text-anchor="middle"
            font-family="'Noto Sans SC', sans-serif" font-size="7" fill="#6b7280">
            {{ isZh ? '筛选占比' : 'filtered' }}
          </text>
        </svg>
      </div>

      <!-- 堆叠条 -->
      <div class="sc-bars">
        <div v-for="lv in levelEntries" :key="lv.key" class="sc-bar-row">
          <span class="sc-bar-label" :style="{ color: lv.color }">{{ lv.label }} {{ lv.count }}</span>
          <div class="sc-bar-track" :style="{ backgroundColor: lv.bg }">
            <div class="sc-bar-fill" :style="{ width: lv.pct + '%', backgroundColor: lv.color }"></div>
          </div>
        </div>
      </div>
    </div>

    <div class="sc-divider"></div>

    <!-- 5. 主题列表 -->
    <div v-if="data.topTopics.length" class="sc-news-section">
      <div class="sc-news-title">{{ isZh ? '热门主题' : 'Top Topics' }}</div>
      <div v-for="(topic, i) in data.topTopics" :key="i" class="sc-news-row">
        <span class="sc-news-score" :style="{ color: levelColor(topic.topLevel) }">{{ topic.maxScore.toFixed(1) }}</span>
        <div class="sc-news-info">
          <div class="sc-news-headline">{{ isZh ? topic.labelZh : topic.labelEn }}</div>
          <div class="sc-news-meta">{{ topic.newsCount }} {{ isZh ? '条新闻' : 'news' }}</div>
        </div>
      </div>
    </div>

    <!-- 6. 页脚 -->
    <div class="sc-divider"></div>
    <div class="sc-footer">
      <div class="sc-footer-note">{{ isZh ? '基于当前筛选条件生成' : 'Based on current filters' }}</div>
      <div class="sc-footer-brand">OPENNEWS</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ShareData } from '@/types'

const props = defineProps<{ data: ShareData }>()

const rootRef = ref<HTMLDivElement>()

const isZh = computed(() => props.data.lang === 'zh')

const generatedTime = computed(() => {
  try {
    const d = new Date(props.data.generatedAt)
    return d.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
  } catch {
    return props.data.generatedAt
  }
})

// 环图计算（r=28）
const circumference = 2 * Math.PI * 28
const dashArray = computed(() => {
  const ratio = Math.min(1, Math.max(0, props.data.filteredRatio / 100))
  const dash = ratio * circumference
  return `${dash.toFixed(1)} ${(circumference - dash).toFixed(1)}`
})
const dashOffset = computed(() => (circumference * 0.25).toFixed(1))

// 堆叠条
const levelEntries = computed(() => {
  const fl = props.data.filteredLevels
  const total = (fl['高'] + fl['中'] + fl['低']) || 1
  return [
    { key: '高', label: isZh.value ? '高' : 'High', count: fl['高'], pct: (fl['高'] / total) * 100, color: '#ef4444', bg: '#fde8e8' },
    { key: '中', label: isZh.value ? '中' : 'Mid', count: fl['中'], pct: (fl['中'] / total) * 100, color: '#f59e0b', bg: '#fef3cd' },
    { key: '低', label: isZh.value ? '低' : 'Low', count: fl['低'], pct: (fl['低'] / total) * 100, color: '#22c55e', bg: '#d1fae5' },
  ]
})

function levelColor(level: string): string {
  if (level === '高') return '#ef4444'
  if (level === '中') return '#f59e0b'
  return '#22c55e'
}

defineExpose({ rootRef })
</script>
