// B03 全链路 E2E：出库拣货（FIFO）→ 提交 → 库存守恒 → 离线补传 → 幂等。
// 用法：node tools/e2e-b03.mjs <outDir>    E2E_BASE 指向被测站点
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const OUT = process.argv[2] ?? '/tmp/wms-b03'
const BASE = process.env.E2E_BASE ?? 'http://localhost:5173'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9336

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
  const f = r?.body?.data?.fields
  return `code=${r?.body?.code} ${r?.body?.message ?? ''}` + (f ? ` fields=${JSON.stringify(f)}` : '')
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

  const token = await login(cdp, 'wangjf')
  check('仓管员登录成功', !!token)
  if (!token) throw new Error('拿不到 token')
  const adminToken = await login(cdp, 'admin')
  check('管理员登录成功', !!adminToken)

  // ---------- 库位用仓管员自己的视野取 ----------
  // 必须用 wangjf 的 token：它只可见 WH-001/WH-002，用 admin 的视野会选到
  // WH-003 的危品库位，后续 FIFO 和补传都会因数据权限看不到而失败。
  const locs = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, token))
  const loc = locs.body.data.items.find(
    (l) => !l.coord_missing && l.status === 'IDLE' && l.type !== 'DANGEROUS')
  const locId = loc?.id
  check('取到仓管员可见的普通库位', !!locId, `${loc?.code ?? ''} (${loc?.warehouse_name ?? ''})`)
  // ---------- 无库存时 FIFO 报缺口 ----------
  const so = await cdp.eval(api('GET', '/api/v1/outbound-orders?no=SO20260127001', null, token))
  const soId = so.body.data.items[0].id
  const fifoEmpty = await cdp.eval(api('GET', `/api/v1/outbound-orders/${soId}/fifo`, null, token))
  check('无库存时 FIFO 报缺口', fifoEmpty.body.data.shortage === 20,
        `缺口 ${fifoEmpty.body.data.shortage}`)

  // ---------- 铺库存：走产品入库单 PI20260127001（MES 推送类型，计划 40） ----------
  const pi = await cdp.eval(api('GET', '/api/v1/inbound-orders?no=PI20260127001', null, token))
  const piId = pi.body.data.items[0].id
  await cdp.eval(api('POST', `/api/v1/inbound-orders/${piId}/scan`,
    { box_code: `BOX-B03-${Date.now().toString(36).toUpperCase()}`, location_id: locId, qty: 40 },
    token))
  const piSub = await cdp.eval(api('POST', `/api/v1/inbound-orders/${piId}/submit`, {}, token))
  check('铺库存：产品入库 40 件', piSub.body.code === '0' && piSub.body.data.status === 'DONE',
        why(piSub))

  const afterIn = await cdp.eval(api('GET', `/api/v1/inventory/products?code=A3288`, null, adminToken))
  const qtyBefore = afterIn.body.data.items[0].qty
  check('铺库存成功', qtyBefore === 40, `A3288 = ${qtyBefore}`)

  // ---------- FIFO 有库存时给出推荐 ----------
  const fifo = await cdp.eval(api('GET', `/api/v1/outbound-orders/${soId}/fifo`, null, token))
  check('有库存时 FIFO 给出推荐', fifo.body.data.shortage === 0 && fifo.body.data.locations.length > 0,
        `${fifo.body.data.locations.length} 个库位`)

  // ---------- 第一批拣货走离线补传（模拟 PDA 断网后补传） ----------
  const syncOpId = 'e2e-b03-sync-' + Date.now().toString(36)
  const pick1 = await cdp.eval(api('POST', '/api/v1/sync/push', {
    ops: [{
      client_op_id: syncOpId,
      op_type: 'OUTBOUND_PICK',
      path: `/api/v1/outbound-orders/${soId}/pick`,
      body: { order_id: soId, location_id: locId, qty: 8 },
      created_at: '2026-11-03T10:00:00Z',
    }],
  }, token))
  const r1 = pick1.body.data?.results?.[0]
  check('离线补传第一批拣货', r1?.status === 'OK', `${r1?.status ?? ''} ${why(pick1)}`)

  const afterSync = await cdp.eval(api('GET', `/api/v1/outbound-orders/${soId}`, null, token))
  check('补传后单据推进部分出库', afterSync.body.data.status === 'PARTIAL' &&
        afterSync.body.data.actual_qty === 8,
        `实发 ${afterSync.body.data.actual_qty}`)

  // ---------- 第二批走正常接口 ----------
  const pick2 = await cdp.eval(api('POST', `/api/v1/outbound-orders/${soId}/pick`,
    { location_id: locId, qty: 12 }, token))
  check('第二批拣货到计划数', pick2.body.code === '0' && pick2.body.data.picked === 20)

  // ---------- 提交出库，库存守恒 ----------
  const sub = await cdp.eval(api('POST', `/api/v1/outbound-orders/${soId}/submit`, {}, token))
  check('提交出库', sub.body.code === '0' && sub.body.data.status === 'DONE',
        `${sub.body.data?.status ?? ''} ${why(sub)}`)

  const afterOut = await cdp.eval(api('GET', `/api/v1/inventory/products?code=A3288`, null, adminToken))
  const qtyAfter = afterOut.body.data.items[0].qty
  check('库存守恒（-20）', qtyAfter === qtyBefore - 20, `${qtyBefore} → ${qtyAfter}`)

  // ---------- 重复补传必须返回 DUPLICATE 且不二次落库 ----------
  const syncAgain = await cdp.eval(api('POST', '/api/v1/sync/push', {
    ops: [{
      client_op_id: syncOpId,
      op_type: 'OUTBOUND_PICK',
      path: `/api/v1/outbound-orders/${soId}/pick`,
      body: { order_id: soId, location_id: locId, qty: 8 },
      created_at: '2026-11-03T10:00:00Z',
    }],
  }, token))
  check('重复补传返回 DUPLICATE',
        syncAgain.body.data?.results?.[0]?.status === 'DUPLICATE',
        `${syncAgain.body.data?.results?.[0]?.status ?? ''}`)
  const afterDup = await cdp.eval(api('GET', `/api/v1/outbound-orders/${soId}`, null, token))
  check('重复补传不二次落库', afterDup.body.data.actual_qty === 20,
        `实发仍为 ${afterDup.body.data.actual_qty}`)

  // ---------- 页面走查 ----------
  await cdp.eval(`localStorage.setItem('wms_token', ${JSON.stringify(adminToken)})`)
  await cdp.send('Page.navigate', { url: `${BASE}/outbound?cb=${Date.now()}` })
  await sleep(2500)
  check('出库管理列表渲染',
        (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 2)
  await cdp.shot('01-outbound-list')

  await cdp.send('Page.navigate', { url: `${BASE}/outbound/${soId}?cb=${Date.now()}` })
  await sleep(2500)
  const txt = await cdp.eval(`document.body.innerText`)
  check('出库详情页展示单据号', txt.includes('SO20260127001'))
  check('详情页展示 FIFO 推荐', txt.includes('FIFO'))
  check('详情页展示已出库状态', txt.includes('已出库'))
  await cdp.shot('02-outbound-detail')
} catch (e) {
  console.error('E2E 异常：', e.message)
  failures++
} finally {
  chrome.kill()
}

console.log(failures === 0 ? '\nB03 E2E 全部通过' : `\nB03 E2E 有 ${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
