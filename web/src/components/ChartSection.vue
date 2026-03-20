<template>
  <section class="chart-section" aria-label="评分分布图与筛选">
    <div class="chart-header">
      <span class="chart-label">{{ summaryText }}</span>
      <span class="chart-range-text" aria-live="polite">{{ rangeLo.toFixed(1) }} — {{ rangeHi.toFixed(1) }}</span>
      <span class="chart-refresh-text" aria-live="polite">{{ refreshText }}</span>
    </div>
    <canvas ref="canvasRef" id="distChart" width="960" height="140" role="img" aria-label="新闻影响评分分布图：横轴为 0-100 分，纵轴为新闻数量"></canvas>
    <div class="range-wrap">
      <div ref="trackRef" class="range-track" @click="onTrackClick">
        <div class="range-fill" :style="fillStyle"></div>
        <div
          v-for="v in dotValues"
          :key="v"
          class="range-dot"
          :style="{ left: v + '%' }"
          :data-val="v"
        ></div>
        <div
          class="range-thumb range-thumb--lo"
          :style="{ left: rangeLo + '%' }"
          tabindex="0"
          @mousedown="dragging = 'lo'"
          @touchstart.passive="dragging = 'lo'"
        ></div>
        <div
          class="range-thumb range-thumb--hi"
          :style="{ left: rangeHi + '%' }"
          tabindex="0"
          @mousedown="dragging = 'hi'"
          @touchstart.passive="dragging = 'hi'"
        ></div>
      </div>
      <div class="range-labels">
        <span v-for="v in dotValues" :key="v">{{ v }}</span>
      </div>
    </div>
    <div class="sort-bar">
      <button
        v-for="s in sortOptions"
        :key="s.value"
        class="sort-btn"
        :class="{ active: sortMode === s.value }"
        @click="$emit('update:sortMode', s.value)"
      >{{ s.label }}</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import type { BatchItem, SortMode, TopicLang, GlobalStats } from '@/types'

const props = defineProps<{
  allItems: BatchItem[]
  globalStats: GlobalStats
  rangeLo: number
  rangeHi: number
  sortMode: SortMode
  topicLang: TopicLang
  summaryScopeText: string
  refreshSecondsLeft: number
}>()

const emit = defineEmits<{
  'update:rangeLo': [v: number]
  'update:rangeHi': [v: number]
  'update:sortMode': [v: SortMode]
}>()

const canvasRef = ref<HTMLCanvasElement>()
const trackRef = ref<HTMLDivElement>()
const dragging = ref<'lo' | 'hi' | null>(null)

const dotValues = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
const sortOptions = computed(() => props.topicLang === 'zh'
  ? [
      { value: 'score' as SortMode, label: '按分数排序' },
      { value: 'time' as SortMode, label: '按时间排序' },
      { value: 'avg' as SortMode, label: '按主题均分排序' },
    ]
  : [
      { value: 'score' as SortMode, label: 'By Score' },
      { value: 'time' as SortMode, label: 'By Time' },
      { value: 'avg' as SortMode, label: 'By Avg Score' },
    ]
)

const fillStyle = computed(() => ({
  left: props.rangeLo + '%',
  width: (props.rangeHi - props.rangeLo) + '%',
}))

const summaryText = computed(() => {
  const total = props.globalStats.total_items
  const above75 = props.globalStats.above75
  if (props.topicLang === 'en') {
    return `In ${props.summaryScopeText}, OPENNEWS analyzed ${total} news articles, ${above75} of which scored above 75.`
  }
  return `在${props.summaryScopeText}内，OPENNEWS 分析了 ${total} 篇新闻文章，其中 ${above75} 篇的评分超过 75 分。`
})

const refreshText = computed(() => {
  if (props.topicLang === 'en') {
    return `Auto refresh in ${props.refreshSecondsLeft}s`
  }
  return `自动刷新：${props.refreshSecondsLeft}s`
})

// ── draw chart ──────────────────────────────────────────
function drawChart() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')!
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr
  ctx.scale(dpr, dpr)
  const W = rect.width
  const H = rect.height
  ctx.clearRect(0, 0, W, H)

  const binCount = 100
  const bins = props.globalStats.score_bins.length === binCount
    ? [...props.globalStats.score_bins]
    : new Array(binCount).fill(0)
  const maxBin = Math.max(...bins, 1)

  const padL = 36, padR = 12, padT = 20, padB = 24
  const plotW = W - padL - padR
  const plotH = H - padT - padB
  const barGap = 1
  const barW = (plotW - barGap * (binCount - 1)) / binCount

  // Y-axis grid
  const yTicks = 4
  ctx.lineWidth = 1
  ctx.font = '500 9px "JetBrains Mono", monospace'
  ctx.textAlign = 'right'
  for (let i = 0; i <= yTicks; i++) {
    const y = padT + plotH - (i / yTicks) * plotH
    ctx.beginPath()
    ctx.setLineDash([3, 4])
    ctx.strokeStyle = 'rgba(107,114,128,0.12)'
    ctx.moveTo(padL, y)
    ctx.lineTo(padL + plotW, y)
    ctx.stroke()
    ctx.setLineDash([])
    const label = Math.round((i / yTicks) * maxBin)
    ctx.fillStyle = 'rgba(107,114,128,0.5)'
    ctx.fillText(String(label), padL - 6, y + 3)
  }

  // bars
  bins.forEach((v, i) => {
    const x = padL + i * (barW + barGap)
    const barH = (v / maxBin) * plotH
    const y = padT + plotH - barH
    const midScore = i + 0.5
    let barColor: string
    if (midScore > 75) barColor = 'rgba(239,68,68,0.75)'
    else if (midScore > 40) barColor = 'rgba(245,158,11,0.75)'
    else barColor = 'rgba(34,197,94,0.75)'
    const inRange = (i + 1) > props.rangeLo && i < props.rangeHi
    if (!inRange) barColor = 'rgba(107,114,128,0.15)'
    ctx.fillStyle = barColor
    ctx.fillRect(x, y, barW, barH)
  })

  // X-axis labels
  ctx.fillStyle = '#6b7280'
  ctx.font = '500 9px "JetBrains Mono", monospace'
  ctx.textAlign = 'center'
  for (let i = 0; i <= 100; i += 10) {
    const x = padL + i * (barW + barGap)
    ctx.fillText(`${i}`, x, padT + plotH + 14)
  }
}

// ── range slider drag ───────────────────────────────────
function getVal(e: MouseEvent | TouchEvent): number {
  const rect = trackRef.value!.getBoundingClientRect()
  const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
  return Math.max(0, Math.min(100, (clientX - rect.left) / rect.width * 100))
}

function onMove(e: MouseEvent | TouchEvent) {
  if (!dragging.value) return
  e.preventDefault()
  const val = Math.round(getVal(e) * 10) / 10
  if (dragging.value === 'lo') {
    emit('update:rangeLo', Math.min(val, props.rangeHi - 1))
  } else {
    emit('update:rangeHi', Math.max(val, props.rangeLo + 1))
  }
}

function onUp() { dragging.value = null }

function onTrackClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target.classList.contains('range-thumb')) return
  if (target.classList.contains('range-dot')) {
    const snapVal = parseInt(target.dataset.val!, 10)
    const distLo = Math.abs(snapVal - props.rangeLo)
    const distHi = Math.abs(snapVal - props.rangeHi)
    if (distLo <= distHi) {
      emit('update:rangeLo', Math.min(snapVal, props.rangeHi - 1))
    } else {
      emit('update:rangeHi', Math.max(snapVal, props.rangeLo + 1))
    }
    return
  }
  const val = Math.round(getVal(e) * 10) / 10
  const distLo = Math.abs(val - props.rangeLo)
  const distHi = Math.abs(val - props.rangeHi)
  if (distLo < distHi) {
    emit('update:rangeLo', Math.min(val, props.rangeHi - 1))
  } else {
    emit('update:rangeHi', Math.max(val, props.rangeLo + 1))
  }
}

// ── lifecycle ───────────────────────────────────────────
watch(() => [props.globalStats, props.rangeLo, props.rangeHi], drawChart, { flush: 'post' })

onMounted(() => {
  drawChart()
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  document.addEventListener('touchmove', onMove, { passive: false })
  document.addEventListener('touchend', onUp)
  window.addEventListener('resize', drawChart)
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onMove)
  document.removeEventListener('mouseup', onUp)
  document.removeEventListener('touchmove', onMove)
  document.removeEventListener('touchend', onUp)
  window.removeEventListener('resize', drawChart)
})

// 暴露 drawChart 供父组件在详情面板开关后调用
defineExpose({ drawChart })
</script>
