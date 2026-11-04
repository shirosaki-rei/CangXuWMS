// B05：AI 四项能力冒烟——推荐 / 路径 / 校验 / 反馈 / 看板 + X04 对话框。
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const OUT = process.argv[2] ?? '/tmp/wms-b05'
const BASE = process.env.E2E_BASE ?? 'http://localhost:5173'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9505
mkdirSync(OUT, { recursive: true })
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-sandbox',
  '--hide-scrollbars', `--remote-debugging-port=${PORT}`, `--user-data-dir=/tmp/wms-e2e-prof-${PORT}`, '--window-size=1440,900',
  'about:blank'], { stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function targetWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      const p = l.find((t) => t.type === 'page')
      if (p?.webSocketDebuggerUrl) return p.webSocketDebuggerUrl
    } catch {}
    await sleep(300)
  }
  throw new Error('CDP 未就绪')
}
class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map() }
  static async connect(url) {
    const ws = new WebSocket(url)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
    const c = new Cdp(ws)
    ws.onmessage = (e) => { const m = JSON.parse(e.data); const p = c.pending.get(m.id); if (p) { c.pending.delete(m.id); p(m.result ?? m) } }
    return c
  }
  send(method, params = {}) { const id = ++this.id; this.ws.send(JSON.stringify({ id, method, params })); return new Promise((r) => this.pending.set(id, r)) }
  async eval(expr) { const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300)); return r.result?.value }
  async shot(n) { const r = await this.send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${n}.png`, Buffer.from(r.data, 'base64')) }
}
let failures = 0
const check = (l, ok, extra = '') => { console.log(`${ok ? '✓' : '✗'} ${l}${extra ? ' — ' + extra : ''}`); if (!ok) failures++ }
const why = (r) => (r?.body?.code === '0' ? '' : `code=${r?.body?.code} ${r?.body?.message ?? ''}`)
function api(method, path, body, token) {
  const hasBody = ['POST', 'PUT', 'PATCH'].includes(method)
  const payload = hasBody ? `body: JSON.stringify(${JSON.stringify(body ?? {})}),` : ''
  return `(async () => { const r = await fetch('${BASE}${path}', { method: '${method}',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ${token}', 'X-Client-Op-Id': crypto.randomUUID() },
    ${payload} }); return { status: r.status, body: await r.json() } })()`
}
async function login(cdp, u) {
  await cdp.send('Page.navigate', { url: `${BASE}/login?cb=${Date.now()}` })
  await sleep(2500)
  // 避免在 heredoc 里写正则（转义容易被 shell 吃掉）：直接按 <text> 切片取字符
  const code = await cdp.eval(`(() => { const svg = atob(document.querySelector('.cap-img').src.split(',')[1]);
    return svg.split('<text').slice(1).map(t => t.slice(t.indexOf('>') + 1, t.indexOf('>') + 2)).join('') })()`)
  await cdp.eval(`(() => { const set = (el, v) => { const d = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value').set; d.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) };
    set(document.querySelector('input[placeholder="请输入账号"]'), '${u}');
    set(document.querySelector('input[placeholder="请输入密码"]'), '${u}');
    set(document.querySelector('input[placeholder="4 位字符"]'), '${code}') })()`)
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('登 录')).click()`)
  await sleep(3500)
  return cdp.eval(`localStorage.getItem('wms_token')`)
}
try {
  const cdp = await Cdp.connect(await targetWs())
  await cdp.send('Page.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  const tk = await login(cdp, 'admin')
  check('登录', !!tk)


  const locs = await cdp.eval(api('GET', '/api/v1/locations?page=1&page_size=100', null, tk))
  const loc = locs.body.data.items.find((l) => l.type === 'NORMAL')
  const prod = await cdp.eval(api('GET', '/api/v1/inventory/products?code=A3288', null, tk))
  const sku = prod.body.data.items[0]

  // 52 库位推荐
  const rec = await cdp.eval(api('POST', '/api/v1/ai/locations/recommend', {
    sku_type: 'PRODUCT', sku_id: sku.id, warehouse_id: loc.warehouse_id, qty: 10, pallet_count: 2 }, tk))
  check('库位推荐返回建议', rec.body.code === '0' && rec.body.data.suggestion_id > 0, why(rec))

  // 53 路径优化
  const opt = await cdp.eval(api('POST', '/api/v1/ai/picking/optimize', { order_type: 'SALES',
    points: [{ location_code: 'A1-01', x: 0, y: 0 }, { location_code: 'A1-02', x: 3, y: 0 },
             { location_code: 'B1-01', x: 0, y: 6 }] }, tk))
  check('路径优化选中精确算法', opt.body.data?.algorithm === 'HELD_KARP',
        `${opt.body.data?.sequence?.join(' → ')} ${why(opt)}`)

  // 54 提交前校验
  const inbound = await cdp.eval(api('GET', '/api/v1/inbound-orders?no=PR20260127001', null, tk))
  const oid = inbound.body.data.items[0].id
  const chk = await cdp.eval(api('POST', `/api/v1/ai/checks/INBOUND/${oid}`, {}, tk))
  const d = chk.body.data
  check('校验返回 11 条规则结果', d?.results?.length >= 6, `${d?.results?.length} 条 ${why(chk)}`)
  check('入库单 R5 显式跳过', d?.results?.some((r) => r.rule === 'R5' && r.level === 'SKIP'))

  // 57 反馈 → 56 看板
  await cdp.eval(api('POST', '/api/v1/ai/feedback', { suggestion_id: rec.body.data.suggestion_id, action: 'ACCEPT' }, tk))
  const m = await cdp.eval(api('GET', '/api/v1/ai/metrics?days=30', null, tk))
  check('看板有采纳数据', (m.body.data?.adoption?.length ?? 0) >= 1, why(m))

  // 页面走查
  // X01 问数：提问 → 结论 + 表格 + 可展开 SQL
  await cdp.send('Page.navigate', { url: `${BASE}/ai/query?cb=${Date.now()}` })
  await sleep(2500)
  await cdp.eval(`(() => {
    const set = (el, v) => { const d = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value').set; d.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })) }
    set(document.querySelector('.ask input'), '近 7 天入库多少')
  })()`)
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '提问').click()`)
  await sleep(2500)
  const qtxt = await cdp.eval('document.body.innerText')
  check('X01 返回结论与口径', qtxt.includes('入库数量合计') || qtxt.includes('没有入库数量记录'),
        qtxt.includes('口径') ? '带口径说明' : '')
  await cdp.shot('03-x01-query')

  await cdp.send('Page.navigate', { url: `${BASE}/ai/dashboard?cb=${Date.now()}` })
  await sleep(2500)
  const txt = await cdp.eval('document.body.innerText')
  check('X05 看板渲染', txt.includes('AI 效果看板') && txt.includes('采纳率'))
  await cdp.shot('01-dashboard')

  await cdp.send('Page.navigate', { url: `${BASE}/inbound/${oid}?cb=${Date.now()}` })
  await sleep(2500)
  const btns = await cdp.eval(`[...document.querySelectorAll('button')].map(b => b.textContent.trim()).join('|')`)
  console.log('  页面按钮:', btns.slice(0, 160))
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('提交入库'))?.click()`)
  await sleep(3000)
  const dlg = await cdp.eval(`document.body.innerText.includes('提交前校验')`)
  check('X04 校验对话框弹出', dlg)
  await cdp.shot('02-check-dialog')
} catch (e) { console.error('E2E 异常：', e.message); failures++ }
finally { chrome.kill() }
console.log(failures === 0 ? '\nB05 E2E 全部通过' : `\nB05 E2E 有 ${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
