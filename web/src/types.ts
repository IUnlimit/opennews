// ── 数据类型定义 ──────────────────────────────────────────

export interface NewsData {
  news_id: string
  title: string
  content?: string
  url?: string
  source?: string
  published_at?: string
}

export interface TopicData {
  topic_id: number
  batch_id: number
  label?: string | { zh?: string; en?: string }
}

export interface ClassificationData {
  category?: string
  all_scores?: Record<string, number>
}

export interface FeaturesData {
  market_impact?: number
  price_signal?: number
  regulatory_risk?: number
  timeliness?: number
  impact?: number
  controversy?: number
  generalizability?: number
  impact_score?: number
}

export interface ReportData {
  final_score?: number
  impact_level?: string
  dk_cot_scores?: Record<string, number>
  reasoning?: string
}

export interface EntityData {
  name: string
  type: string
}

export interface BatchItem {
  news?: NewsData
  topic?: TopicData
  classification?: ClassificationData
  features?: FeaturesData
  report?: ReportData
  entities?: EntityData[]
}

export interface PaginatedResponse {
  items: BatchItem[]
  page: number
  total_pages: number
  total_topics: number
  total_items: number
  above75: number
  score_bins: number[]
  levels: { '高': number; '中': number; '低': number }
}

export interface GlobalStats {
  total_items: number
  above75: number
  score_bins: number[]
  total_topics: number
  levels: { '高': number; '中': number; '低': number }
}

export interface TopicGroup {
  topic_id: string
  label: string
  items: BatchItem[]
}

export type SortMode = 'score' | 'time' | 'avg'
export type TopicLang = 'zh' | 'en'
