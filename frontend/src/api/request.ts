import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { uuidv4 } from '@/utils/uuid'
import { messageOf, isBizError, SILENT_CODES } from '@/utils/errorcode'

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

const http = axios.create({
  baseURL: BASE,
  timeout: 20000,
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})

/** 每次「用户意图」一个 UUID（接口文档 1.3）。实现见 utils/uuid.ts（含非安全上下文的降级）。 */
export function newOpId(): string {
  return uuidv4()
}

http.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
  const token = useUserStore().token
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  const traceId = sessionStorage.getItem('trace_id')
  if (traceId) cfg.headers['X-Trace-Id'] = traceId
  return cfg
})

http.interceptors.response.use(
  (resp) => {
    const traceId = resp.headers['x-trace-id']
    if (traceId) sessionStorage.setItem('trace_id', traceId)

    const body = resp.data
    // 非 JSON（/metrics、文件下载）直接放行
    if (body === null || typeof body !== 'object' || !('code' in body)) return body

    if (body.code === '0') return body.data

    const code = String(body.code)
    if (code === 'WMS-4010') {
      useUserStore().reset()
      location.assign('/login')
      return Promise.reject(body)
    }
    if (!SILENT_CODES.has(code)) {
      ElMessage.error(messageOf(code, body.message))
    }
    return Promise.reject(body)
  },
  (err: AxiosError<{ code?: string; message?: string }>) => {
    const data = err.response?.data
    if (data?.code) {
      if (data.code === 'WMS-4010') {
        useUserStore().reset()
        location.assign('/login')
      } else if (!SILENT_CODES.has(data.code)) {
        ElMessage.error(messageOf(data.code, data.message))
      }
      return Promise.reject(data)
    }
    if (err.code === 'ECONNABORTED') ElMessage.error('请求超时，请稍后重试')
    else if (!err.response) ElMessage.error('网络不通，请检查连接')
    return Promise.reject(err)
  },
)

/** GET：自动带分页参数 */
export function get<T = any>(url: string, params?: Record<string, any>, cfg?: AxiosRequestConfig) {
  return http.get<any, T>(url, { params, ...cfg })
}

/** 写操作：自动生成并注入 X-Client-Op-Id（幂等键，接口文档 1.3） */
export function post<T = any>(url: string, data?: unknown, cfg?: AxiosRequestConfig) {
  return http.post<any, T>(url, data, {
    ...cfg,
    headers: { 'X-Client-Op-Id': newOpId(), ...(cfg?.headers ?? {}) },
  })
}

export function put<T = any>(url: string, data?: unknown, cfg?: AxiosRequestConfig) {
  return http.put<any, T>(url, data, {
    ...cfg,
    headers: { 'X-Client-Op-Id': newOpId(), ...(cfg?.headers ?? {}) },
  })
}

/** 上传文件（导出 CSV 等），不套统一信封 */
export function download(url: string, params?: Record<string, any>) {
  return http.get(url, { params, responseType: 'blob' })
}

export { isBizError }
