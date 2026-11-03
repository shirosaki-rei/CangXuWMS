/** 运行时配置。API 地址可在登录页修改并持久化，方便换现场网段。 */
export const APP_VERSION = '0.1.0'

/** 默认地址：`expo start` 时用 EXPO_PUBLIC_API_BASE 覆盖，例如 http://192.168.1.20:8000/api/v1 */
export const DEFAULT_API_BASE =
  process.env.EXPO_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000/api/v1'

/** 与 PC 端一致的幂等键：每次「用户意图」一个 UUID，落本地队列后不再变 */
export function newOpId(): string {
  // crypto.randomUUID 在 RN 的 Hermes 上不一定有，这里用够用的 v4 生成器
  const hex = '0123456789abcdef'
  let s = ''
  for (let i = 0; i < 36; i++) {
    if (i === 8 || i === 13 || i === 18 || i === 23) s += '-'
    else if (i === 14) s += '4'
    else if (i === 19) s += hex[(Math.random() * 4 | 0) + 8]
    else s += hex[Math.random() * 16 | 0]
  }
  return s
}
