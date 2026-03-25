<template>
  <header class="hdr" role="banner">
    <div class="hdr-left">
      <span class="hdr-logo" aria-hidden="true">
        <svg class="hdr-logo-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8"/>
          <path d="M7 8H17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M7 12H17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
          <path d="M7 16H13" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
          <circle cx="17" cy="16" r="1.4" fill="currentColor"/>
        </svg>
      </span>
      <h1 class="hdr-title">OPENNEWS</h1>
      <span class="hdr-sub">IMPACT TERMINAL</span>
    </div>
    <div class="hdr-center">
      <span class="hdr-stat">{{ stats.total }}</span>
      <span class="hdr-stat-label">{{ topicLang === 'zh' ? '条新闻' : 'news' }}</span>
      <span class="hdr-divider">│</span>
      <span class="hdr-stat">{{ stats.topics }}</span>
      <span class="hdr-stat-label">{{ topicLang === 'zh' ? '个主题' : 'topics' }}</span>
      <span class="hdr-divider">│</span>
      <span class="hdr-badge hdr-badge--high">{{ topicLang === 'zh' ? '高' : 'H' }} {{ stats.high }}</span>
      <span class="hdr-badge hdr-badge--mid">{{ topicLang === 'zh' ? '中' : 'M' }} {{ stats.mid }}</span>
      <span class="hdr-badge hdr-badge--low">{{ topicLang === 'zh' ? '低' : 'L' }} {{ stats.low }}</span>
    </div>
    <div class="hdr-right">
      <button
        class="share-btn"
        :class="{ loading: sharing }"
        :disabled="sharing"
        :title="topicLang === 'zh' ? '生成分享图片' : 'Generate share image'"
        @click="$emit('share')"
      >
        <svg v-if="!sharing" class="share-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
          <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
        </svg>
        <svg v-else class="share-icon share-icon--spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
      </button>
      <a
        class="github-link"
        href="https://github.com/IUnlimit/opennews"
        target="_blank"
        rel="noopener noreferrer"
        :title="topicLang === 'zh' ? '在 GitHub 上查看源码' : 'View source on GitHub'"
      >
        <svg class="github-icon" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
        </svg>
      </a>
    </div>
  </header>
</template>

<script setup lang="ts">
import type { TopicLang } from '@/types'

defineProps<{
  topicLang: TopicLang
  stats: { total: number; topics: number; high: number; mid: number; low: number }
  sharing: boolean
}>()

defineEmits<{ share: [] }>()
</script>
