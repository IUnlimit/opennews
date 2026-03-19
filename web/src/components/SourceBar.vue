<template>
  <div class="source-bar">
    <label class="source-label">{{ topicLang === 'zh' ? '数据源' : 'Source' }}</label>
    <select id="sourceSelect" :value="modelValue" @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)">
      <option value="hours:1">{{ topicLang === 'zh' ? '近 1 小时' : 'Last 1 hour' }}</option>
      <option value="hours:3">{{ topicLang === 'zh' ? '近 3 小时' : 'Last 3 hours' }}</option>
      <option value="hours:12">{{ topicLang === 'zh' ? '近 12 小时' : 'Last 12 hours' }}</option>
      <option value="hours:24">{{ topicLang === 'zh' ? '近 1 天' : 'Last 1 day' }}</option>
      <option value="hours:72">{{ topicLang === 'zh' ? '近 3 天' : 'Last 3 days' }}</option>
      <option value="hours:168">{{ topicLang === 'zh' ? '近 7 天' : 'Last 7 days' }}</option>
    </select>
    <button class="source-btn" @click="$emit('load')">{{ topicLang === 'zh' ? '加载' : 'Load' }}</button>
    <input ref="fileInput" type="file" accept=".json" style="display:none" @change="onFileChange">
    <button class="source-btn" @click="($refs.fileInput as HTMLInputElement).click()">{{ topicLang === 'zh' ? '导入 JSON' : 'Import JSON' }}</button>

    <span class="source-spacer"></span>

    <!-- Language switch -->
    <div class="lang-switch-bar">
      <button
        v-for="lang in (['zh', 'en'] as const)"
        :key="lang"
        class="lang-btn-bar"
        :class="{ active: topicLang === lang }"
        :title="lang === 'zh' ? '中文主题' : 'English topics'"
        @click="$emit('update:topicLang', lang)"
      >
        <span class="lang-btn-icon">{{ lang === 'zh' ? '中' : 'A' }}</span>
        <span class="lang-btn-text">{{ lang === 'zh' ? '中文' : 'EN' }}</span>
      </button>
    </div>

    <!-- Theme toggle -->
    <button class="theme-toggle-bar" :title="topicLang === 'zh' ? '切换日间/夜间模式' : 'Toggle light/dark mode'" @click="onToggleTheme">
      <svg class="theme-icon theme-icon--sun" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      <svg class="theme-icon theme-icon--moon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, inject } from 'vue'
import type { BatchItem, TopicLang } from '@/types'

defineProps<{ modelValue: string; topicLang: TopicLang }>()
const emit = defineEmits<{
  'update:modelValue': [val: string]
  'update:topicLang': [lang: TopicLang]
  load: []
  importJson: [items: BatchItem[]]
}>()

const onToggleTheme = inject<() => void>('toggleTheme')!

const fileInput = ref<HTMLInputElement>()

function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result as string)
      const items = (Array.isArray(data) ? data : data.items || []).filter(
        (d: any) => d.news && d.report
      )
      emit('importJson', items)
    } catch (err: any) {
      alert('JSON 解析失败: ' + err.message)
    }
  }
  reader.readAsText(file)
}
</script>
