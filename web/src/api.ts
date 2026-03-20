import type { BatchItem, PaginatedResponse } from './types'

export async function fetchRecords(
  hours: number,
  page: number,
  scoreLo: number = 0,
  scoreHi: number = 100,
): Promise<PaginatedResponse> {
  const resp = await fetch(
    `/api/records?hours=${hours}&page=${page}&score_lo=${scoreLo}&score_hi=${scoreHi}`,
  )
  if (!resp.ok) throw new Error('no data')
  const data = await resp.json()

  // 兼容分页响应和旧的纯数组格式
  if (Array.isArray(data)) {
    return {
      items: data, page: 1, total_pages: 1, total_topics: 0,
      total_items: data.length, above75: 0, score_bins: [], levels: { '高': 0, '中': 0, '低': 0 },
    }
  }
  return {
    items: data.items || [],
    page: data.page || 1,
    total_pages: data.total_pages || 1,
    total_topics: data.total_topics || 0,
    total_items: data.total_items || 0,
    above75: data.above75 || 0,
    score_bins: data.score_bins || [],
    levels: data.levels || { '高': 0, '中': 0, '低': 0 },
  }
}

export async function fetchBatch(batchId: string): Promise<BatchItem[]> {
  const resp = await fetch(`/api/batches/${batchId}`)
  if (!resp.ok) throw new Error('no data')
  return resp.json()
}
