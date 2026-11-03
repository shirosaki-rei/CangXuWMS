/**
 * 离线队列（T-01-7）。
 *
 * 一行 = 一次「用户意图」，client_op_id 在入队时就定死、永不变更——
 * 这样存量重放、APP 重启、断网重连，服务端都能靠它去重（接口 1.3 / ADR-004）。
 */
import * as SQLite from 'expo-sqlite'
import { NetworkError, ApiError, request } from '../api/client'
import { BATCH_SIZE, chunk, removable, summarize } from './queueLogic'

export type OpStatus = 'PENDING' | 'FAILED'

export interface PendingOp {
  client_op_id: string
  op_type: string
  path: string
  body: string
  created_at: string
  status: OpStatus
  error: string | null
  /** 已尝试补传次数，用于界面上标「重试 3 次」 */
  retries: number
}

export interface OpInput {
  clientOpId: string
  opType: string
  path: string
  body: unknown
  createdAt?: string
}

let db: SQLite.SQLiteDatabase | null = null

export async function initQueue(): Promise<void> {
  if (db) return
  db = await SQLite.openDatabaseAsync('wms_queue.db')
  await db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS pending_ops (
      client_op_id TEXT PRIMARY KEY NOT NULL,
      op_type      TEXT NOT NULL,
      path         TEXT NOT NULL,
      body         TEXT NOT NULL,
      created_at   TEXT NOT NULL,
      status       TEXT NOT NULL DEFAULT 'PENDING',
      error        TEXT,
      retries      INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_pending_created ON pending_ops(status, created_at);
  `)
}

function need(): SQLite.SQLiteDatabase {
  if (!db) throw new Error('队列尚未初始化，先调用 initQueue()')
  return db
}

export async function enqueue(input: OpInput): Promise<void> {
  await need().runAsync(
    `INSERT OR IGNORE INTO pending_ops
       (client_op_id, op_type, path, body, created_at, status, error, retries)
     VALUES (?, ?, ?, ?, ?, 'PENDING', NULL, 0)`,
    [
      input.clientOpId,
      input.opType,
      input.path,
      JSON.stringify(input.body ?? {}),
      input.createdAt ?? new Date().toISOString(),
    ],
  )
}

export async function listOps(): Promise<PendingOp[]> {
  return need().getAllAsync<PendingOp>(
    'SELECT * FROM pending_ops ORDER BY created_at ASC',
  )
}

export async function countOps(): Promise<{ pending: number; failed: number }> {
  const rows = await need().getAllAsync<{ status: OpStatus; n: number }>(
    'SELECT status, COUNT(*) AS n FROM pending_ops GROUP BY status',
  )
  const out = { pending: 0, failed: 0 }
  for (const r of rows) {
    if (r.status === 'PENDING') out.pending = r.n
    if (r.status === 'FAILED') out.failed = r.n
  }
  return out
}

export async function removeOp(clientOpId: string): Promise<void> {
  await need().runAsync('DELETE FROM pending_ops WHERE client_op_id = ?', [clientOpId])
}

async function markFailed(clientOpId: string, error: string): Promise<void> {
  await need().runAsync(
    `UPDATE pending_ops SET status = 'FAILED', error = ?, retries = retries + 1
     WHERE client_op_id = ?`,
    [error, clientOpId],
  )
}

/** 重试：把 FAILED 改回 PENDING，下次 flush 再试 */
export async function retryFailed(): Promise<void> {
  await need().runAsync(
    `UPDATE pending_ops SET status = 'PENDING', error = NULL WHERE status = 'FAILED'`,
  )
}

export interface FlushResult {
  total: number
  ok: number
  duplicate: number
  failed: number
  error?: string
}

/**
 * 补传到 /sync/push（接口 58）。
 * 单条失败不影响后续（BR-012）；OK / DUPLICATE 直接删本地，FAILED 留着重试。
 */
export async function flush(apiBase: string, token: string): Promise<FlushResult> {
  const ops = await listOps()
  const res: FlushResult = { total: ops.length, ok: 0, duplicate: 0, failed: 0 }
  if (!ops.length) return res

  for (const batch of chunk(ops)) {
    let out: SyncOut
    try {
      const r = await request<SyncOut>({
        base: apiBase,
        token,
        method: 'POST',
        path: '/sync/push',
        body: {
          ops: batch.map((o) => ({
            client_op_id: o.client_op_id,
            op_type: o.op_type,
            path: o.path,
            body: JSON.parse(o.body),
            created_at: o.created_at,
          })),
        },
      })
      out = r.data
    } catch (e) {
      if (e instanceof NetworkError) {
        res.error = '网络不通，稍后自动重试'
        break
      }
      if (e instanceof ApiError) {
        res.error = `${e.code} ${e.message}`
        break
      }
      res.error = String(e)
      break
    }

    const sum = summarize(out.results)
    res.ok += sum.ok
    res.duplicate += sum.duplicate
    res.failed += sum.failed
    for (const r of out.results) {
      if (removable(r)) await removeOp(r.client_op_id)
      else await markFailed(r.client_op_id, `${r.http_code} ${r.message ?? ''}`.trim())
    }
  }
  return res
}

interface SyncOut {
  results: { client_op_id: string; status: 'OK' | 'DUPLICATE' | 'FAILED'; http_code: string; message?: string }[]
  total: number
}
