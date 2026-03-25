<template>
  <div class="layout">
    <div class="shell">
      <AppHeader
        :topic-lang="topicLang"
        :stats="stats"
        :sharing="sharing"
        @share="handleShare"
      />
      <ChartSection
        ref="chartRef"
        :all-items="allItems"
        :global-stats="globalStats"
        :range-lo="rangeLo"
        :range-hi="rangeHi"
        :sort-mode="sortMode"
        :topic-lang="topicLang"
        :summary-scope-text="summaryScopeText"
        :refresh-seconds-left="refreshSecondsLeft"
        @update:range-lo="rangeLo = $event; debouncedApplyFilter()"
        @update:range-hi="rangeHi = $event; debouncedApplyFilter()"
        @update:sort-mode="sortMode = $event"
      />
      <TopicList
        ref="topicListRef"
        :items="filteredItems"
        :sort-mode="sortMode"
        :topic-lang="topicLang"
        :active-news-id="activeNewsId"
        :open-topics="openTopics"
        :empty-text="emptyText"
        @select-news="showDetail"
      />
      <PaginationBar
        :current-page="currentPage"
        :total-pages="totalPages"
        @go="goToPage"
      />
    </div>
    <DetailPanel
      :item="detailItem"
      @close="closeDetail"
    />
  </div>
  <SourceBar
    v-model="source"
    :topic-lang="topicLang"
    @load="onSourceLoad"
    @import-json="onImportJson"
    @update:topic-lang="topicLang = $event"
  />

  <!-- 分享卡片（隐藏，仅用于截图） -->
  <div class="share-offscreen" aria-hidden="true">
    <ShareSnapshot v-if="showShareCard" ref="shareRef" :data="shareData" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted, provide, nextTick } from 'vue'
import type { BatchItem, SortMode, TopicLang, GlobalStats, ShareData } from '@/types'
import { fetchRecords, fetchBatch } from '@/api'
import { useTheme } from '@/composables/useTheme'
import { useAutoRefresh } from '@/composables/useAutoRefresh'
import { domToPngBlob, shareOrDownload } from '@/utils/share'
import { getTopicLabel } from '@/utils'

import AppHeader from '@/components/AppHeader.vue'
import ChartSection from '@/components/ChartSection.vue'
import TopicList from '@/components/TopicList.vue'
import PaginationBar from '@/components/PaginationBar.vue'
import DetailPanel from '@/components/DetailPanel.vue'
import SourceBar from '@/components/SourceBar.vue'
import ShareSnapshot from '@/components/ShareSnapshot.vue'

// ── theme ───────────────────────────────────────────────
const { toggle: toggleTheme } = useTheme()
provide('toggleTheme', toggleTheme)

// ── state ───────────────────────────────────────────────
const allItems = ref<BatchItem[]>([])
const filteredItems = ref<BatchItem[]>([])
const rangeLo = ref(50)
const rangeHi = ref(100)
const sortMode = ref<SortMode>('score')
const topicLang = ref<TopicLang>((localStorage.getItem('topicLang') as TopicLang) || 'en')
const activeNewsId = ref<string | null>(null)
const source = ref('hours:24')
const currentPage = ref(1)
const totalPages = ref(1)
const totalTopics = ref(0)
const globalStats = ref<GlobalStats>({
  total_items: 0, above75: 0, score_bins: [], total_topics: 0,
  levels: { '高': 0, '中': 0, '低': 0 },
})
const openTopics = reactive(new Set<string>())
const emptyText = ref('加载中…')

const chartRef = ref<InstanceType<typeof ChartSection>>()
const topicListRef = ref<InstanceType<typeof TopicList>>()

// ── share ────────────────────────────────────────────────
const sharing = ref(false)
const showShareCard = ref(false)
const shareRef = ref<InstanceType<typeof ShareSnapshot>>()

const shareData = computed<ShareData>(() => {
  const g = globalStats.value
  const items = filteredItems.value
  const total = g.total_items || 1
  const filteredCount = items.length
  const filteredRatio = (filteredCount / total) * 100

  // 筛选结果内的高/中/低分布
  const fl = { '高': 0, '中': 0, '低': 0 } as { '高': number; '中': number; '低': number }
  items.forEach(d => {
    const lv = d.report?.impact_level
    if (lv && lv in fl) fl[lv as keyof typeof fl]++
  })

  // 按主题聚合，取 top 5 主题（按主题内最高分降序）
  const topicMap = new Map<string, { labelZh: string; labelEn: string; maxScore: number; newsCount: number; topLevel: string }>()
  items.forEach(d => {
    const tid = d.topic?.topic_id ?? -1
    const bid = d.topic?.batch_id ?? 0
    const key = `${bid}:${tid}`
    const score = d.report?.final_score ?? 0
    const level = d.report?.impact_level ?? '低'
    const labelZh = getTopicLabel(d.topic, 'zh')
    const labelEn = getTopicLabel(d.topic, 'en')
    if (!topicMap.has(key)) {
      topicMap.set(key, { labelZh, labelEn, maxScore: score, newsCount: 1, topLevel: level })
    } else {
      const t = topicMap.get(key)!
      t.newsCount++
      if (score > t.maxScore) {
        t.maxScore = score
        t.topLevel = level
      }
    }
  })
  const topTopics = [...topicMap.values()]
    .sort((a, b) => b.maxScore - a.maxScore)
    .slice(0, 5)

  return {
    lang: topicLang.value,
    generatedAt: new Date().toISOString(),
    scopeText: summaryScopeText.value,
    scoreRange: `${rangeLo.value.toFixed(0)}–${rangeHi.value.toFixed(0)}`,
    totalItems: g.total_items,
    filteredCount,
    filteredRatio: Math.round(filteredRatio * 10) / 10,
    above75: g.above75,
    levels: g.levels,
    filteredLevels: fl,
    topTopics,
  }
})

async function handleShare() {
  if (sharing.value) return
  sharing.value = true
  showShareCard.value = true

  try {
    // 等待 DOM 渲染
    await nextTick()
    await new Promise(r => setTimeout(r, 100))

    const el = shareRef.value?.rootRef
    if (!el) throw new Error('share card not ready')

    const blob = await domToPngBlob(el)
    await shareOrDownload(blob)
  } catch (err) {
    console.error('share failed:', err)
  } finally {
    sharing.value = false
    showShareCard.value = false
  }
}
// ── persist lang ────────────────────────────────────────
watch(topicLang, (v) => localStorage.setItem('topicLang', v))

// ── stats ───────────────────────────────────────────────
const stats = computed(() => {
  const g = globalStats.value
  return {
    total: g.total_items,
    topics: g.total_topics,
    high: g.levels['高'],
    mid: g.levels['中'],
    low: g.levels['低'],
  }
})

const summaryScopeText = computed(() => {
  if (source.value.startsWith('hours:')) {
    const hours = Number.parseFloat(source.value.slice(6))
    if (!Number.isFinite(hours) || hours <= 0) {
      return topicLang.value === 'zh' ? '当前时间范围' : 'the selected time range'
    }
    if (topicLang.value === 'zh') {
      if (hours < 24) return `最近 ${hours} 小时`
      if (hours % 24 === 0) return `最近 ${hours / 24} 天`
      return `最近 ${hours} 小时`
    }
    if (hours < 24) return `the last ${hours} hour${hours === 1 ? '' : 's'}`
    if (hours % 24 === 0) {
      const days = hours / 24
      return `the last ${days} day${days === 1 ? '' : 's'}`
    }
    return `the last ${hours} hours`
  }
  return topicLang.value === 'zh' ? '当前数据集' : 'the current dataset'
})

// ── detail ──────────────────────────────────────────────
const detailItem = ref<BatchItem | null>(null)

function showDetail(nid: string) {
  const item = allItems.value.find(d => d.news?.news_id === nid)
  if (!item) return
  activeNewsId.value = nid
  detailItem.value = item
  setTimeout(() => chartRef.value?.drawChart(), 380)
}

function closeDetail() {
  detailItem.value = null
  activeNewsId.value = null
  setTimeout(() => chartRef.value?.drawChart(), 380)
}

// close on Escape
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && detailItem.value) closeDetail()
}

// ── filter ──────────────────────────────────────────────
function applyFilter() {
  // hours 模式下由后端筛选，重新请求第1页
  if (source.value.startsWith('hours:')) {
    currentPage.value = 1
    loadData(undefined, 1)
    return
  }
  // batch / import 模式下仍在前端过滤
  filteredItems.value = allItems.value.filter(d => {
    const s = d.report?.final_score ?? 0
    return s >= rangeLo.value && s <= rangeHi.value
  })
}

// 防抖版 applyFilter，用于滑块拖动（避免频繁请求后端）
let _filterTimer: ReturnType<typeof setTimeout> | null = null
function debouncedApplyFilter() {
  // batch / import 模式无需防抖，直接过滤
  if (!source.value.startsWith('hours:')) {
    applyFilter()
    return
  }
  if (_filterTimer) clearTimeout(_filterTimer)
  _filterTimer = setTimeout(() => {
    _filterTimer = null
    applyFilter()
  }, 350)
}

// ── data loading ────────────────────────────────────────
async function loadData(src?: string, page?: number) {
  const s = src ?? source.value
  try {
    if (s.startsWith('hours:')) {
      const h = parseFloat(s.slice(6))
      const p = page ?? currentPage.value
      const result = await fetchRecords(h, p, rangeLo.value, rangeHi.value)
      allItems.value = result.items.filter(d => d.news && d.report)
      filteredItems.value = allItems.value  // 后端已筛选，直接使用
      currentPage.value = result.page
      totalPages.value = result.total_pages
      totalTopics.value = result.total_topics
      globalStats.value = {
        total_items: result.total_items,
        above75: result.above75,
        score_bins: result.score_bins,
        total_topics: result.total_topics,
        levels: result.levels,
      }
    } else if (s.startsWith('batch:')) {
      const items = await fetchBatch(s.slice(6))
      allItems.value = items.filter(d => d.news && d.report)
      currentPage.value = 1
      totalPages.value = 1
      totalTopics.value = 0
      // batch 模式下从本地数据计算全局统计
      const batchItems = allItems.value
      const bins = new Array(100).fill(0)
      const lvls = { '高': 0, '中': 0, '低': 0 } as Record<string, number>
      let a75 = 0
      const topicSet = new Set<number>()
      batchItems.forEach(d => {
        const score = d.report?.final_score ?? 0
        bins[Math.min(99, Math.max(0, Math.floor(score)))]++
        if (score >= 75) a75++
        const level = d.report?.impact_level
        if (level && level in lvls) lvls[level]++
        if (d.topic?.topic_id != null) topicSet.add(d.topic.topic_id)
      })
      globalStats.value = {
        total_items: batchItems.length,
        above75: a75,
        score_bins: bins,
        total_topics: topicSet.size,
        levels: { '高': lvls['高'] || 0, '中': lvls['中'] || 0, '低': lvls['低'] || 0 },
      }
    }

    if (allItems.value.length === 0) {
      emptyText.value = '所选时间范围内无数据'
    }

    // batch / import 模式需要前端过滤；hours 模式后端已筛选
    if (!s.startsWith('hours:')) {
      filteredItems.value = allItems.value.filter(d => {
        const sc = d.report?.final_score ?? 0
        return sc >= rangeLo.value && sc <= rangeHi.value
      })
    }

    // 自动刷新时保持详情面板
    if (activeNewsId.value) {
      const still = allItems.value.find(d => d.news?.news_id === activeNewsId.value)
      if (still) detailItem.value = still
    }
  } catch {
    allItems.value = []
    filteredItems.value = []
    currentPage.value = 1
    totalPages.value = 1
    totalTopics.value = 0
    globalStats.value = {
      total_items: 0, above75: 0, score_bins: [], total_topics: 0,
      levels: { '高': 0, '中': 0, '低': 0 },
    }
    emptyText.value = '暂无数据 — 请先运行后端流水线产出批次数据'
  }
}

// ── pagination ──────────────────────────────────────────
function goToPage(page: number) {
  if (page < 1 || page > totalPages.value || page === currentPage.value) return
  currentPage.value = page
  loadData(undefined, page)
  nextTick(() => {
    document.querySelector('.topics')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

// ── source bar events ───────────────────────────────────
function onSourceLoad() {
  currentPage.value = 1
  loadData(source.value, 1)
  autoRefresh.start()
}

function onImportJson(items: BatchItem[]) {
  allItems.value = items
  currentPage.value = 1
  totalPages.value = 1
  totalTopics.value = 0
  // 从导入数据计算全局统计
  const bins = new Array(100).fill(0)
  const lvls = { '高': 0, '中': 0, '低': 0 } as Record<string, number>
  let a75 = 0
  const topicSet = new Set<number>()
  items.forEach(d => {
    const score = d.report?.final_score ?? 0
    bins[Math.min(99, Math.max(0, Math.floor(score)))]++
    if (score >= 75) a75++
    const level = d.report?.impact_level
    if (level && level in lvls) lvls[level]++
    if (d.topic?.topic_id != null) topicSet.add(d.topic.topic_id)
  })
  globalStats.value = {
    total_items: items.length,
    above75: a75,
    score_bins: bins,
    total_topics: topicSet.size,
    levels: { '高': lvls['高'] || 0, '中': lvls['中'] || 0, '低': lvls['低'] || 0 },
  }
  applyFilter()
}

watch(source, () => {
  currentPage.value = 1
  loadData(source.value, 1)
  autoRefresh.start()
})

// ── auto refresh ────────────────────────────────────────
const autoRefresh = useAutoRefresh(() => loadData())
const refreshSecondsLeft = computed(() => autoRefresh.secondsLeft.value)

// ── lifecycle ───────────────────────────────────────────
onMounted(async () => {
  document.addEventListener('keydown', onKeydown)
  await loadData()
  autoRefresh.start()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>
