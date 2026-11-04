import { get, post } from './request'

export interface CheckItem {
  rule: string
  level: 'PASS' | 'WARN' | 'BLOCK' | 'LOG' | 'SKIP' | 'TIMEOUT'
  title: string
  detail?: string
  actions?: string[]
}

export interface CheckResult {
  summary: { pass: number; warn: number; block: number; timeout: number; skipped: number }
  submittable: boolean
  results: CheckItem[]
  cache_hit: boolean
  elapsed_ms: number
  suggestion_id: number
}

export interface RecommendResult {
  primary: {
    location_id: number
    location_code: string
    confidence: string
    score: number
    reasons: string[]
  } | null
  alternatives: { location_id: number; location_code: string; score: number; note: string }[]
  degraded: boolean
  confidence: string
  reason: string | null
  suggestion_id: number
}

export interface Metrics {
  window_days: number
  suggestion_total: number
  adoption: { type: string; accept: number; reject: number; revoke: number; rate: number | null }[]
  scenes: {
    scene: string
    avg_duration_ms: number
    avg_distance_m: number
    avg_baseline_m: number
    saved_pct: number | null
    count: number
  }[]
  offline_threshold: number
}

export const LEVEL_TAG: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  PASS: 'success',
  WARN: 'warning',
  BLOCK: 'danger',
  LOG: 'info',
  SKIP: 'info',
  TIMEOUT: 'warning',
}

export const LEVEL_LABEL: Record<string, string> = {
  PASS: '通过', WARN: '预警', BLOCK: '阻断', LOG: '记录', SKIP: '不适用', TIMEOUT: '超时',
}

export const aiApi = {
  recommend: (body: {
    sku_type: string
    sku_id: number
    warehouse_id: number
    qty: number
    pallet_count: number
    order_id?: number
  }) => post<RecommendResult>('/ai/locations/recommend', body),
  checks: (orderType: string, id: number) =>
    post<CheckResult>(`/ai/checks/${orderType}/${id}`, {}),
  feedback: (suggestionId: number, action: 'ACCEPT' | 'REJECT' | 'REVOKE', reason?: string) =>
    post('/ai/feedback', { suggestion_id: suggestionId, action, reason }),
  metrics: (days = 30) => get<Metrics>('/ai/metrics', { days }),
}
