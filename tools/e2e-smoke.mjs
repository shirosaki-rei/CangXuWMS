// 极简 CDP 驱动：启动 headless Chrome，跑通「登录 → 工作台 → 仓库管理」并截图。
// 用法：node tools/e2e-smoke.mjs <outDir>
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
// WebSocket 用 Node 22+ 的全局实现，无需额外依赖

const OUT = process.argv[2] ?? '/tmp/wms-e2e'
// E2E_BASE 指向被测站点：5173 是 vite dev，8080 是 docker compose 的 nginx
const URL_BASE = process.env.E2E_BASE ?? 'http://localhost:5173'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9333

mkdirSync(OUT, { recursive: true })

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, '--window-size=1440,900',
  'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function targetWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`)
      const list = await r.json()
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
      const msg = JSON.parse(e.data)
      const p = c.pending.get(msg.id)
      if (p) { c.pending.delete(msg.id); p(msg.result ?? msg) }
    }
    return c
  }
  send(method, params = {}) {
    const id = ++this.id
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((res) => this.pending.set(id, res))
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', {
      expression: expr, returnByValue: true, awaitPromise: true,
    })
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails))
    return r.result?.value
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(`${OUT}/${name}.png`, Buffer.from(r.data, 'base64'))
    return `${OUT}/${name}.png`
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
  await cdp.send('Network.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })

  // 1. 打开登录页（带 cache buster，避免同 URL 命中缓存）
  await cdp.send('Page.navigate', { url: `${URL_BASE}/login?cb=${Date.now()}` })
  await sleep(2500)
  const hasForm = await cdp.eval(`!!document.querySelector('input[placeholder="请输入账号"]')`)
  check('登录页渲染', hasForm)
  await cdp.shot('01-login')

  // 2. 读验证码图片 → 从 SVG 里取字符
  const code = await cdp.eval(`(() => {
    const img = document.querySelector('.cap-img')
    if (!img) return null
    const svg = atob(img.src.split(',')[1])
    return (svg.match(/<text[^>]*>([A-Z0-9])<\\/text>/g) || [])
      .map(s => s.replace(/.*>([A-Z0-9])<.*/, '$1')).join('')
  })()`)
  check('验证码可解码', !!code && code.length === 4, code)

  // 3. 填表登录（Vue 需要 input 事件触发响应式）
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
  const url = await cdp.eval('location.pathname')
  check('登录成功并跳转', url !== '/login', url)
  await cdp.shot('02-dashboard')

  // 4. 侧边菜单应只剩有权限的项（admin 全有）
  const menuCount = await cdp.eval(`document.querySelectorAll('.side a').length`)
  check('菜单渲染', menuCount >= 6, `${menuCount} 项`)

  // 5. 仓库管理
  await cdp.eval(`location.href = '/basedata/warehouse'`)
  await sleep(2500)
  const whRows = await cdp.eval(`document.querySelectorAll('.el-table__row').length`)
  check('仓库列表有数据', whRows >= 3, `${whRows} 行`)
  await cdp.shot('03-warehouse')

  // 6. 库位管理（含分页）
  await cdp.eval(`location.href = '/basedata/location'`)
  await sleep(2500)
  const locTotal = await cdp.eval(`document.querySelector('.el-pagination__total')?.textContent`)
  check('库位列表分页', !!locTotal, locTotal)
  await cdp.shot('04-location')

  // 7. 权限矩阵
  await cdp.eval(`location.href = '/system/role'`)
  await sleep(2500)
  const matrixRows = await cdp.eval(`document.querySelectorAll('.el-table__row').length`)
  check('权限矩阵渲染', matrixRows >= 17, `${matrixRows} 行`)
  await cdp.shot('05-roles')

  // 8. 新增仓库（走幂等头）——用唯一编码，避免与上一轮残留数据撞唯一键
  await cdp.eval(`location.href = '/basedata/warehouse'`)
  await sleep(2000)
  const before = await cdp.eval(`document.querySelectorAll('.el-table__row').length`)
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('新增仓库')).click()`)
  await sleep(800)
  const newCode = 'WH-E2E-' + Date.now().toString(36).toUpperCase()
  await cdp.eval(`(() => {
    const set = (el, v) => {
      const d = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value').set
      d.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    set(document.querySelector('input[placeholder="WH-001"]'), '${newCode}')
    set(document.querySelector('input[placeholder="1#原料仓"]'), 'E2E测试仓')
  })()`)
  await cdp.eval(`[...document.querySelectorAll('.el-dialog__footer button')].find(b => b.textContent === '保存').click()`)
  await sleep(2500)
  const after = await cdp.eval(`document.querySelectorAll('.el-table__row').length`)
  const firstCode = await cdp.eval(`document.querySelector('.el-table__row td .cell')?.textContent`)
  check('新增仓库成功', after === before + 1 && firstCode === newCode, `${before} → ${after} 行，首行 ${firstCode}`)
  await cdp.shot('06-warehouse-created')

  // 9. 退出登录
  await cdp.eval(`[...document.querySelectorAll('button')].find(b => b.textContent === '退出').click()`)
  await sleep(600)
  await cdp.eval(`[...document.querySelectorAll('.el-message-box button')].find(b => b.textContent === '确定').click()`)
  await sleep(2500)
  const afterLogout = await cdp.eval('location.pathname')
  check('退出回到登录页', afterLogout === '/login', afterLogout)
} catch (e) {
  console.error('E2E 异常：', e.message)
  failures++
} finally {
  chrome.kill()
}

console.log(failures === 0 ? '\nE2E 全部通过' : `\nE2E 有 ${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
