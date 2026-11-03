// 移动端离线队列的纯逻辑自检（不含 SQLite）。Node 22+ 原生剥类型。
import { BATCH_SIZE, chunk, removable, summarize } from '../mobile/src/db/queueLogic.ts'
import { newOpId } from '../mobile/src/config.ts'

const assert = (ok, msg) => { if (!ok) throw new Error('queue self-check failed: ' + msg) }

// 1) 分批：单批不超过服务端上限，且不丢、不乱序
assert(BATCH_SIZE === 50, '上限应与接口文档 5.5 一致')
assert(JSON.stringify(chunk([])) === '[]', '空数组应无批次')
assert(chunk(Array(50)).length === 1, '50 条应 1 批')
assert(chunk(Array(51)).length === 2, '51 条应 2 批')
const sizes = chunk(Array(137)).map((b) => b.length)
assert(JSON.stringify(sizes) === '[50,50,37]', `137 条切片不对：${sizes}`)
const ordered = Array.from({ length: 137 }, (_, i) => i)
const flat = chunk(ordered).flat()
assert(JSON.stringify(flat) === JSON.stringify(ordered), '切片后顺序必须不变（补传按扫码时间先后）')

// 2) 结果归类：OK/DUPLICATE 可删，FAILED 保留
const rs = [
  { client_op_id: 'a', status: 'OK', http_code: '0' },
  { client_op_id: 'b', status: 'DUPLICATE', http_code: 'WMS-4091' },
  { client_op_id: 'c', status: 'FAILED', http_code: 'WMS-4222', message: '库存不足' },
]
const s = summarize(rs)
assert(s.ok === 1 && s.duplicate === 1 && s.failed === 1, `归类不对：${JSON.stringify(s)}`)
assert(removable(rs[0]) && removable(rs[1]) && !removable(rs[2]), 'removable 判定不对')

// 3) 幂等键：必须是合法 UUID v4 形状且不重复（服务端靠它去重）
const seen = new Set()
for (let i = 0; i < 2000; i++) {
  const id = newOpId()
  assert(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id),
    `不是合法的 UUID v4：${id}`)
  assert(!seen.has(id), `重复的幂等键：${id}`)
  seen.add(id)
}

console.log('mobile queue self-check ok')
