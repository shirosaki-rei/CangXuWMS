/**
 * 队列里与平台无关的纯逻辑，单独放出来是为了能在 Node 里跑检查
 * （expo-sqlite 只能在设备上跑，fetch 依赖也同理）。
 */

export interface SyncResult {
  client_op_id: string
  status: 'OK' | 'DUPLICATE' | 'FAILED'
  http_code: string
  message?: string
}

export interface Summary {
  ok: number
  duplicate: number
  failed: number
}

/** 接口文档 5.5：/sync/push 单次 ≤ 50 条 */
export const BATCH_SIZE = 50

/** 按上限切片，保持原顺序（补传必须按扫码时间先后） */
export function chunk<T>(arr: T[], size: number = BATCH_SIZE): T[][] {
  const out: T[][] = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}

/**
 * OK / DUPLICATE 都可以从本地删掉（重复说明服务端已处理过）；
 * 只有 FAILED 要留着并累计重试次数。
 */
export function summarize(results: SyncResult[]): Summary {
  const s: Summary = { ok: 0, duplicate: 0, failed: 0 }
  for (const r of results) {
    if (r.status === 'OK') s.ok++
    else if (r.status === 'DUPLICATE') s.duplicate++
    else s.failed++
  }
  return s
}

/** 哪些可以从本地删掉 */
export function removable(r: SyncResult): boolean {
  return r.status === 'OK' || r.status === 'DUPLICATE'
}
