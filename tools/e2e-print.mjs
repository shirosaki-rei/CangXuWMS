// 条码打印页冒烟：登录 → 条码管理 → 全选 → 批量打印 → 截图预览。
// 用法：node tools/e2e-print.mjs <outDir>
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'

const OUT = process.argv[2] ?? '/tmp/wms-print'
const BASE = process.env.E2E_BASE ?? 'http://localhost:5173'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9506

mkdirSync(OUT, { recursive: true })
const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=/tmp/wms-e2e-prof-${PORT}`, '--window-size=1440,900', 'about:blank',
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

try {
  const cdp = await Cdp.connect(await targetWs())
  await cdp.send('Page.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })

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
    set(document.querySelector('input[placeholder="请输入账号"]'), 'admin')
    set(document.querySelector('input[placeholder="请输入密码"]'), 'admin')
    set(document.querySelector('input[placeholder="4 位字符"]'), '${code}')
  })()`)
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('登 录')).click()`)
  await sleep(3500)

  await cdp.send('Page.navigate', { url: `${BASE}/basedata/barcode?cb=${Date.now()}` })
  await sleep(2500)
  const rows = await cdp.eval(`document.querySelectorAll('.el-table__row').length`)
  check('条码列表有数据', rows >= 4, `${rows} 行`)

  // 全选
  await cdp.eval(`document.querySelector('.el-table__header .el-checkbox')?.click()`)
  await sleep(500)

  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('批量打印')).click()`)
  await sleep(1200)

  const labelCount = await cdp.eval(`document.querySelectorAll('.label').length`)
  check('打印预览生成了标签', labelCount >= 4, `${labelCount} 张`)

  const svgCount = await cdp.eval(`document.querySelectorAll('.label-barcode svg rect').length`)
  check('每张标签有 bar 矩形', svgCount > 0, `${svgCount} 个 rect`)

  // 检查 SVG 宽度是否真的铺满标签（能被扫到的前提）
  const box = await cdp.eval(`(() => {
    const el = document.querySelector('.label-barcode svg')
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { w: Math.round(r.width), h: Math.round(r.height) }
  })()`)
  check('条码渲染尺寸合理', !!box && box.w > 40 && box.h > 10,
        box ? `${box.w}×${box.h}px` : '无')

  await cdp.shot('01-print-dialog')

  // 换成 60x40 再截一张
  await cdp.eval(`[...document.querySelectorAll('.el-radio')].find(r => r.textContent.includes('60×40'))?.click()`)
  await sleep(600)
  await cdp.shot('02-print-60x40')
  check('切换规格后预览仍在', (await cdp.eval(`document.querySelectorAll('.label.p-60x40').length`)) >= 4)
} catch (e) {
  console.error('E2E 异常：', e.message)
  failures++
} finally {
  chrome.kill()
}

console.log(failures === 0 ? '\n条码打印冒烟全部通过' : `\n条码打印冒烟有 ${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
