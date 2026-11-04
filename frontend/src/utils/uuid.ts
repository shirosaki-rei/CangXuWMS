/**
 * UUID v4。
 *
 * `crypto.randomUUID` 只在安全上下文（https / localhost）存在；仓库现场常用
 * `http://192.168.x.x` 打开，此时它不存在，直接调用会抛异常。
 * 幂等键在请求拦截器里生成，异常发生在 fetch 之前——表现为「点登录没反应」，
 * 且没有任何网络请求，非常难查。所以这里必须有降级实现。
 */
export function uuidv4(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const hex = '0123456789abcdef'
  let s = ''
  for (let i = 0; i < 36; i++) {
    if (i === 8 || i === 13 || i === 18 || i === 23) s += '-'
    else if (i === 14) s += '4'
    else if (i === 19) s += hex[((Math.random() * 4) | 0) + 8]
    else s += hex[(Math.random() * 16) | 0]
  }
  return s
}
