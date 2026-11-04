// 幂等键生成器自检。非安全上下文（http://局域网IP）下必须仍然可用。
import { uuidv4 } from '../frontend/src/utils/uuid.ts'

const assert = (ok, msg) => { if (!ok) throw new Error('uuid self-check failed: ' + msg) }
const re = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

const seen = new Set()
for (let i = 0; i < 2000; i++) {
  const id = uuidv4()
  assert(re.test(id), `非法 UUID：${id}`)
  assert(!seen.has(id), `重复：${id}`)
  seen.add(id)
}

// 模拟非安全上下文：把 crypto.randomUUID 抠掉，必须走降级分支。
// globalThis.crypto 只有 getter，改不了整个对象，只能改它的属性。
const saved = globalThis.crypto?.randomUUID
try {
  Object.defineProperty(globalThis.crypto, 'randomUUID', {
    value: undefined, configurable: true, writable: true,
  })
  const id = uuidv4()
  assert(re.test(id), `降级分支产出的不是 UUID v4：${id}`)
} finally {
  if (saved) {
    Object.defineProperty(globalThis.crypto, 'randomUUID', {
      value: saved, configurable: true, writable: true,
    })
  }
}

console.log('uuid self-check ok')
