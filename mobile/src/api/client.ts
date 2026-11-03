/** 与 PC 端同一套响应信封：{ code, message, data, trace_id }（接口文档 1.1）。 */
import { newOpId } from '../config'

export interface Envelope<T> {
  code: string
  message: string
  data: T
  trace_id: string
}

export class ApiError extends Error {
  code: string
  status: number
  constructor(code: string, message: string, status = 0) {
    super(message)
    this.code = code
    this.status = status
  }
}

/** 网络层失败（不是业务失败）：这类才能进离线队列重试 */
export class NetworkError extends Error {}

export interface ReqOpts {
  base: string
  token?: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  body?: unknown
  /** 写操作的幂等键；不传则自动生成。**每次请求都必须新生成**——
   *  复用会让服务端把第二次当成第一次的重放，直接返回旧结果 */
  opId?: string
  timeoutMs?: number
}

export interface ReqResult<T> {
  code: string
  data: T
  opId: string
  elapsedMs: number
}

/** 单次请求。业务错误抛 ApiError，连不上/超时抛 NetworkError。 */
export async function request<T>(o: ReqOpts): Promise<ReqResult<T>> {
  const opId = o.opId ?? newOpId()
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), o.timeoutMs ?? 10000)
  const started = Date.now()

  let resp: Response
  try {
    resp = await fetch(`${o.base}${o.path}`, {
      method: o.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'X-Client-Op-Id': opId,
        ...(o.token ? { Authorization: `Bearer ${o.token}` } : {}),
      },
      body: o.body === undefined ? undefined : JSON.stringify(o.body),
      signal: ctrl.signal,
    })
  } catch (e) {
    throw new NetworkError(`连不上服务器：${(e as Error).message}`)
  } finally {
    clearTimeout(timer)
  }

  const elapsedMs = Date.now() - started
  let env: Envelope<T>
  try {
    env = (await resp.json()) as Envelope<T>
  } catch {
    throw new ApiError('WMS-5000', `响应不是 JSON（HTTP ${resp.status}）`, resp.status)
  }

  if (env.code !== '0') {
    throw new ApiError(env.code, env.message ?? '请求失败', resp.status)
  }
  return { code: env.code, data: env.data, opId, elapsedMs }
}
