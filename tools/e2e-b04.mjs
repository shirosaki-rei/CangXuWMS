// B04 全链路 E2E：铺物料库存 → 创建盘点（锁库位）→ 实盘 → 提交 → 盈亏单据 + 库存调整 + 解锁。
// 用法：node tools/e2e-b04.mjs <outDir>
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const OUT = process.argv[2] ?? '/tmp/wms-b04'
const BASE = process.env.E2E_BASE ?? 'http://localhost:5173'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9338

mkdirSync(OUT, { recursive: true })
const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function targetWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      const page = list.find((t) => t.type === 'page')
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch {}
    await sleep(300)
  }
  throw new Error('Chrome CDP 未就绪')
}

class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map() }
  static async connect(url) {
    const ws = new WebSocket(url)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
    const c = new Cdp(ws)
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data)
      const p = c.pending.get(m.id)
      if (p) { c.pending.delete(m.id); p(m.result ?? m) }
    }
    return c
  }
  send(method, params = {}) {
    const id = ++this.id
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((res) => this.pending.set(id, res))
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate',
      { expression: expr, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300))
    return r.result?.value
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.data, 'base64'))
  }
}

let failures = 0
function check(label, ok, extra = '') {
  console.log(`${ok ? '✓' : '✗'} ${label}${extra ? ' — ' + extra : ''}`)
  if (!ok) failures++
}
function why(r) {
  if (r?.body?.code === '0') return ''
  return `code=${r?.body?.code} ${r?.body?.message ?? ''}`
}

async function login(cdp, username) {
  await cdp.send('Page.navigate', { url: `${BASE}/login?cb=${Date.now()}` })
  await sleep(2500)
  const code = await cdp.eval(`(() => {
    const svg = atob(document.querySelector('.cap-img').src.split(',')[1])
    return (svg.match(/<text[^>]*>([A-Z0-9])<\\/text>/g) || [])
      .map(s => s.replace(/.*>([A-Z0-9])<.*/, '$1')).join('')
  })()`)
  await cdp.eval(`(() => {
    const set = (el, v) => {
      const d = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value').set
      d.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    set(document.querySelector('input[placeholder="请输入账号"]'), '${username}')
    set(document.querySelector('input[placeholder="请输入密码"]'), '${username}')
    set(document.querySelector('input[placeholder="4 位字符"]'), '${code}')
  })()`)
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('登 录')).click()`)
  await sleep(3500)
  return cdp.eval(`localStorage.getItem('wms_token')`)
}

function api(method, path, body, token) {
  const hasBody = ['POST', 'PUT', 'PATCH'].includes(method)
  const payload = hasBody ? `body: JSON.stringify(${JSON.stringify(body ?? {})}),` : ''
  return `(async () => {
    const r = await fetch('${BASE}${path}', {
      method: '${method}',
      headers: { 'Content-Type': 'application/json',
                 'Authorization': 'Bearer ${token}',
                 'X-Client-Op-Id': crypto.randomUUID() },
      ${payload}
    })
    return { status: r.status, body: await r.json() }
  })()`
}

try {
  const cdp = await Cdp.connect(await targetWs())
  await cdp.send('Page.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })

  const adminToken = await login(cdp, 'admin')
  check('管理员登录', !!adminToken)
  const shToken = await login(cdp, 'supervisor')
  check('主管登录', !!shToken)

  // ---------- 铺物料库存：采购入库单 PR20260127001 ----------
  const locs = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, adminToken))
  // 必须是普通库位：危品库位会被 BR-013 拦掉（成品/普通物料不能进）
  const loc = locs.body.data.items.find(
    (l) => l.coord_missing === false && l.status === 'IDLE' && l.type === 'NORMAL')
  const pr = await cdp.eval(api('GET', '/api/v1/inbound-orders?no=PR20260127001', null, adminToken))
  const prId = pr.body.data.items[0].id
  const mat = await cdp.eval(api('GET', '/api/v1/inspections/2', null, adminToken))
  const prScan = await cdp.eval(api('POST', `/api/v1/inbound-orders/${prId}/scan`,
    { box_code: 'BOX-B04-' + Date.now().toString(36).toUpperCase(), location_id: loc.id, qty: 200 },
    adminToken))
  check('采购入库扫码', prScan.body.code === '0',
        `${loc.code} ${why(prScan)}`)
  const prSub = await cdp.eval(api('POST', `/api/v1/inbound-orders/${prId}/submit`, {}, adminToken))
  check('采购入库提交', prSub.body.code === '0', why(prSub))
  const before = await cdp.eval(api('GET', '/api/v1/inventory/materials', null, adminToken))
  const row = before.body.data.items.find((m) => m.qty > 0)
  check('物料库存已就绪', !!row, row ? `${row.code} = ${row.qty}` : '')
  if (!row) throw new Error('没有物料库存，无法盘点')

  // ---------- 创建盘点单（接口 32） ----------
  const whId = loc.warehouse_id
  const created = await cdp.eval(api('POST', '/api/v1/stocktakes', {
    warehouse_id: whId, type: 'FULL', mode: 'BLIND',
  }, shToken))
  check('创建盘点单并锁定库位', created.body.code === '0',
        `${created.body.data?.no ?? ''} ${why(created)}`)
  const sid = created.body.data.id
  const stNo = created.body.data.no

  const lockedAfterCreate = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, shToken))
  check('库位已锁定（BR-007）',
        lockedAfterCreate.body.data.items.some((l) => l.warehouse_id === whId && l.status === 'LOCKED'))

  // ---------- 盲盘：仓管员看不到账面 ----------
  await cdp.eval(`localStorage.setItem('wms_token', ${JSON.stringify(shToken)})`)
  const itemsSh = await cdp.eval(api('GET', `/api/v1/stocktakes/${sid}/items`, null, shToken))
  check('主管可见账面', itemsSh.body.data.every((i) => i.book_qty !== undefined),
        `${itemsSh.body.data.length} 行`)

  const keeperToken = await login(cdp, 'wangjf')
  const itemsK = await cdp.eval(api('GET', `/api/v1/stocktakes/${sid}/items`, null, keeperToken))
  check('仓管员盲盘看不到账面', itemsK.body.data.every((i) => i.book_qty === undefined))

  // ---------- 实盘：一亏一平 ----------
  const rows = itemsSh.body.data
  check('盘点单有明细', rows.length >= 1, `${rows.length} 行`)
  // 第一行盘亏 5，其余按账面原值盘平
  for (let i = 0; i < rows.length; i++) {
    const r0 = rows[i]
    const real = i === 0 ? Math.max(0, r0.book_qty - 5) : r0.book_qty
    const res = await cdp.eval(api('POST', `/api/v1/stocktakes/${sid}/count`, {
      location_id: r0.location_id, material_id: r0.material_id, real_qty: real,
    }, keeperToken))
    if (i === 0) check('实盘录入', res.body.code === '0', `实盘 ${real} / 账面 ${r0.book_qty} ${why(res)}`)
  }

  const afterCount = await cdp.eval(api('GET', `/api/v1/stocktakes/${sid}`, null, shToken))
  check('全部盘完转待确认', afterCount.body.data.status === 'CONFIRMING',
        `${afterCount.body.data.done}/${afterCount.body.data.total}`)

  // ---------- 提交（接口 31） ----------
  const submitted = await cdp.eval(api('POST', `/api/v1/stocktakes/${sid}/submit`, {}, shToken))
  const d = submitted.body.data
  check('提交盘点生成盈亏单据', submitted.body.code === '0' && d?.status === 'DONE',
        `${d?.loss_no ?? '无盘亏单'} / ${d?.gain_no ?? '无盘盈单'} ${why(submitted)}`)
  check('盘亏 1 条', d?.diff_loss === 1, `loss=${d?.diff_loss}`)

  const after = await cdp.eval(api('GET', '/api/v1/inventory/materials', null, adminToken))
  const rowAfter = after.body.data.items.find((m) => m.code === row.code)
  check('库存已按盘亏调整', rowAfter.qty === row.qty - 5, `${row.qty} → ${rowAfter.qty}`)

  const unlocked = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, shToken))
  check('提交后解锁库位',
        !unlocked.body.data.items.some((l) => l.warehouse_id === whId && l.status === 'LOCKED'))

  // ---------- 移位 ----------
  // 用 admin 的视野取库位：仓管员只被分配到 WH-001/002，
  // 而库存可能落在 WH-003，用仓管员 token 会查不到目标库位
  const locs2 = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, adminToken))
  const two = locs2.body.data.items.filter(
    (l) => l.warehouse_id === whId && l.id !== loc.id && l.status === 'IDLE' && l.type === 'NORMAL')
  const moved = await cdp.eval(api('POST', '/api/v1/move-orders', {
    material_id: row.id, from_location_id: loc.id, to_location_id: two[0].id, qty: 10,
  }, adminToken))
  check('移位成功', moved.body.code === '0', `${moved.body.data?.no ?? ''} ${why(moved)}`)

  // ---------- 页面走查 ----------
  await cdp.eval(`localStorage.setItem('wms_token', ${JSON.stringify(shToken)})`)
  await cdp.send('Page.navigate', { url: `${BASE}/stocktake?cb=${Date.now()}` })
  await sleep(2500)
  check('盘点列表渲染', (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 1)
  await cdp.shot('01-stocktake-list')

  await cdp.send('Page.navigate', { url: `${BASE}/stocktake/${sid}?cb=${Date.now()}` })
  await sleep(2500)
  const txt = await cdp.eval('document.body.innerText')
  check('盘点详情展示单号', txt.includes(stNo))
  check('详情展示已完成', txt.includes('已完成'))
  await cdp.shot('02-stocktake-detail')

  await cdp.send('Page.navigate', { url: `${BASE}/move?cb=${Date.now()}` })
  await sleep(2500)
  check('移位列表渲染', (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 1)
  await cdp.shot('03-move-list')

  await cdp.send('Page.navigate', { url: `${BASE}/basedata/supplier?cb=${Date.now()}` })
  await sleep(2500)
  check('供应商页渲染', (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 3)
  await cdp.shot('04-supplier')
} catch (e) {
  console.error('E2E 异常：', e.message)
  failures++
} finally {
  chrome.kill()
}

console.log(failures === 0 ? '\nB04 E2E 全部通过' : `\nB04 E2E 有 ${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
