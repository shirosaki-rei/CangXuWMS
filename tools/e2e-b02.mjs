// B02 全链路 E2E：登录 → 库存查询 → 来料检验扫码/判定 → 生成入库单 → 扫码收货 → 提交 → 库存守恒。
// 用法：node tools/e2e-b02.mjs <outDir>    E2E_BASE 指向被测站点（默认 localhost:5173）
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const OUT = process.argv[2] ?? '/tmp/wms-b02'
const BASE = process.env.E2E_BASE ?? 'http://localhost:5173'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9334

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

/** 接口调用失败时把 message 带进 extra，方便定位 */
function why(r) {
  return r?.body?.code === '0' ? '' : `code=${r?.body?.code} ${r?.body?.message ?? ''}`
}

/** 用指定账号登录，返回 token */
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

/** 在页面上下文里带 Bearer 调后端：比点页面快，且能覆盖接口层 */
function api(method, path, body, token) {
  // 判断必须放在模板外：${...} 表达式里的 '${method}' 是字面量，不会被二次插值
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

  // ---------- 登录：liq 走检验接口，admin 走页面 ----------
  const token = await login(cdp, 'liq')
  check('检验员登录成功', !!token)
  if (!token) throw new Error('拿不到 token，后续无法继续')
  const adminToken = await login(cdp, 'admin')
  check('管理员登录成功', !!adminToken)
  if (!adminToken) throw new Error('拿不到 admin token')

  // ---------- 页面走查用 admin（liq 只被分配到 WH-001，无库存时列表为空） ----------
  await cdp.eval(`localStorage.setItem('wms_token', ${JSON.stringify(adminToken)})`)
  await cdp.send('Page.navigate', { url: `${BASE}/inventory/material?cb=${Date.now()}` })
  await sleep(2500)
  check('物料库存列表有数据',
        (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 6)
  await cdp.shot('01-material-stock')

  await cdp.send('Page.navigate', { url: `${BASE}/inventory/product?cb=${Date.now()}` })
  await sleep(2500)
  check('成品库存列表有数据',
        (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 4)
  await cdp.shot('02-product-stock')

  await cdp.send('Page.navigate', { url: `${BASE}/txn/material?cb=${Date.now()}` })
  await sleep(2500)
  check('物料流水页渲染', !!(await cdp.eval(`document.body.innerText.includes('物料出入库查询')`)))
  await cdp.shot('03-txn')

  // ---------- 来料检验：扫码 → 判定 → 生成入库单 ----------
  const insp = await cdp.eval(api('GET', '/api/v1/inspections?no=JY20260127001', null, token))
  const iid = insp.body?.data?.items?.[0]?.id
  check('取到待检检验单', !!iid, `id=${iid}`)
  if (!iid) throw new Error('没有待检检验单，先跑 app.seed')
  // 列表不带明细，物料 id 要从详情拿
  const detail = await cdp.eval(api('GET', `/api/v1/inspections/${iid}`, null, token))
  const mat = detail.body?.data?.items?.[0]
  check('取到检验明细物料', !!mat, mat ? `${mat.material_code}` : '')
  const before = await cdp.eval(api('GET', '/api/v1/inventory/materials', null, token))
  const matBefore = before.body.data.items.find((m) => m.code === 'BAT-LIPO-4500-003')

  const scanR = await cdp.eval(api('POST', `/api/v1/inspections/${iid}/scan`,
    { material_id: mat.material_id, actual_qty: 300 }, token))
  check('来料检验扫码', scanR.body.code === '0' && scanR.body.data.status === 'CHECKING',
        `实收 ${scanR.body.data?.scanned ?? why(scanR)}`)

  const judgeR = await cdp.eval(api('POST', `/api/v1/inspections/${iid}/judge`,
    { result: 'PASS' }, token))
  check('判定合格', judgeR.body.code === '0' && judgeR.body.data.result === 'PASS',
        why(judgeR))

  const genR = await cdp.eval(api('POST', `/api/v1/inspections/${iid}/gen-inbound`, null, token))
  check('生成采购入库单', genR.body.code === '0', `${genR.body.data?.no ?? ''} ${why(genR)}`)
  const orderId = genR.body.data?.order_id
  const orderNo = genR.body.data?.no

  // ---------- 扫码收货 → 提交 ----------
  const locs = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, token))
  const locId = locs.body.data.items.find((l) => !l.coord_missing)?.id
  check('取到上架库位', !!locId, `location_id=${locId}`)

  const inScan = await cdp.eval(api('POST', `/api/v1/inbound-orders/${orderId}/scan`,
    { box_code: `BOX-E2E-${Date.now().toString(36).toUpperCase()}`, location_id: locId, qty: 300 },
    token))
  check('入库扫码收货', inScan.body.code === '0' && inScan.body.data.scanned === 300,
        `状态 ${inScan.body.data?.status ?? ''} ${why(inScan)}`)

  const submitR = await cdp.eval(api('POST', `/api/v1/inbound-orders/${orderId}/submit`, {}, token))
  check('提交入库落库', submitR.body.code === '0' && submitR.body.data.status === 'DONE',
        `${submitR.body.data?.status ?? ''} ${why(submitR)}`)

  // ---------- 库存守恒 ----------
  const after = await cdp.eval(api('GET', '/api/v1/inventory/materials', null, token))
  const matAfter = after.body.data.items.find((m) => m.code === 'BAT-LIPO-4500-003')
  check('库存守恒（+300）',
        matAfter.qty === (matBefore?.qty ?? 0) + 300,
        `${matBefore?.qty} → ${matAfter.qty}`)

  const txnR = await cdp.eval(api('GET', `/api/v1/txn?sku_type=MATERIAL&biz_type=PURCHASE_IN`,
    null, token))
  const row = txnR.body.data.items.find((t) => t.biz_no === orderNo)
  check('流水记录了本次入库', !!row && row.qty_delta === 300 && row.balance === matAfter.qty,
        `结存 ${row?.balance}`)

  // ---------- 页面走查 ----------
  await cdp.send('Page.navigate', { url: `${BASE}/inbound?cb=${Date.now()}` })
  await sleep(2500)
  check('入库管理列表渲染',
        (await cdp.eval(`document.querySelectorAll('.el-table__row').length`)) >= 1)
  await cdp.shot('04-inbound-list')

  await cdp.send('Page.navigate', { url: `${BASE}/inbound/${orderId}?cb=${Date.now()}` })
  await sleep(2500)
  const detailText = await cdp.eval(`document.body.innerText`)
  check('入库详情页展示单据号', detailText.includes(orderNo))
  check('详情页展示已入库状态', detailText.includes('已入库'))
  await cdp.shot('05-inbound-detail')

  await cdp.send('Page.navigate', { url: `${BASE}/inspection?cb=${Date.now()}` })
  await sleep(2500)
  check('来料检验页渲染', (await cdp.eval(`document.body.innerText.includes('来料检验')`)))
  await cdp.shot('06-inspection')
} catch (e) {
  console.error('E2E 异常：', e.message)
  failures++
} finally {
  chrome.kill()
}

console.log(failures === 0 ? '\nB02 E2E 全部通过' : `\nB02 E2E 有 ${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
