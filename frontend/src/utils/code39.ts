/**
 * Code 39 条码 → SVG。
 *
 * 为什么不用库：Code 39 的编码表就 43 项、9 个元素/字符，一个表加 30 行渲染就够，
 * 为它引一个 barcode 依赖不划算。为什么选 Code 39 而不是 Code 128：
 * 标签 40×30mm 放 6–8 位编码绰绰有余，而 Code 128 要多一张 107 项的码表。
 *
 * 每个字符 9 个元素，从「条」开始、以「条」结束，交织为 条/空/条/空/…/条。
 * 1=宽（3 单位），0=窄（1 单位）；字符之间空 1 个窄单位。
 */
const CODES: Record<string, string> = {
  '0': '000110100', '1': '100100001', '2': '001100001', '3': '101100000',
  '4': '000110001', '5': '100110000', '6': '001110000', '7': '000100101',
  '8': '100100100', '9': '001100100',
  A: '100001001', B: '001001001', C: '101001000', D: '000011001',
  E: '100011000', F: '001011000', G: '000001101', H: '100001100',
  I: '001001100', J: '000011100', K: '100000011', L: '001000011',
  M: '101000010', N: '000010011', O: '100010010', P: '001010010',
  Q: '000000111', R: '100000110', S: '001000110', T: '000010110',
  U: '110000001', V: '011000001', W: '111000000', X: '010010001',
  Y: '110010000', Z: '011010000',
  '-': '010000101', '.': '110000100', ' ': '011000100',
  '$': '010101000', '/': '010100010', '+': '010001010', '%': '000101010',
  '*': '010010100', // start / stop
}

const NARROW = 1
const WIDE = 3
const GAP = 1

/** 只接受 Code 39 字符集；小写自动转大写 */
export function canEncode(code: string): boolean {
  return /^[0-9A-Z\-. $/+%]+$/.test(code.toUpperCase())
}

export interface BarcodeSvg {
  /** SVG 源码，可直接 innerHTML */
  svg: string
  /** 宽高比（宽/高），用于按标签宽度算高度 */
  ratio: number
}

/** 生成条码主体（不含文字）。height 相对单位，宽度按元素自动算。 */
export function code39Svg(raw: string, opts: { height?: number; showText?: boolean } = {}): BarcodeSvg {
  const text = raw.toUpperCase()
  const height = opts.height ?? 40
  const chars = `*${text}*`.split('')

  // 先算总宽度（单位），再一次性构造 rect
  const units: { x: number; w: number; isBar: boolean }[] = []
  let x = 0
  chars.forEach((ch, idx) => {
    const pat = CODES[ch]
    if (!pat) throw new Error(`Code 39 不支持的字符：${ch}`)
    for (let i = 0; i < 9; i++) {
      const w = pat[i] === '1' ? WIDE : NARROW
      const isBar = i % 2 === 0
      units.push({ x, w, isBar })
      x += w
    }
    if (idx < chars.length - 1) x += GAP
  })

  const totalW = x
  const textH = opts.showText === false ? 0 : 11
  const rects = units
    .filter((u) => u.isBar)
    .map((u) => `<rect x="${u.x}" y="0" width="${u.w}" height="${height}"/>`)
    .join('')

  const label = opts.showText === false
    ? ''
    : `<text x="${totalW / 2}" y="${height + 9}" font-family="Consolas,monospace"
             font-size="8" text-anchor="middle" fill="#000">${escapeXml(text)}</text>`

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalW} ${height + textH}" ` +
    `preserveAspectRatio="none" width="100%" height="100%" fill="#000">${rects}${label}</svg>`

  return { svg, ratio: totalW / (height + textH) }
}

/**
 * 自检：`node tools/check-code39.mjs`（Node 22+ 原生剥类型）跑它。
 * 校验的是「码表本身 + 宽度算术」，不是渲染效果。
 */
export function selfCheck(): void {
  const assert = (ok: boolean, msg: string) => {
    if (!ok) throw new Error('code39 self-check failed: ' + msg)
  }

  // 1) 码表：每个字符 9 位、恰好 3 个宽元素（Code 39 的结构性约束）
  for (const [ch, pat] of Object.entries(CODES)) {
    assert(pat.length === 9, `${ch} 长度 ${pat.length}`)
    assert(/^[01]+$/.test(pat), `${ch} 含非 0/1`)
    const wide = [...pat].filter((c) => c === '1').length
    assert(wide === 3, `${ch} 宽元素 ${wide} 个（应为 3）`)
  }
  // 43 个数据字符 + 起止符 '*' = 44
  assert(Object.keys(CODES).length === 44, `字符集应 44 项，实际 ${Object.keys(CODES).length}`)

  // 2) 抽查几个公开编码（与 Wikipedia Code 39 表一致）
  assert(CODES['0'] === '000110100', '0')
  assert(CODES['A'] === '100001001', 'A')
  assert(CODES['*'] === '010010100', '* (start/stop)')
  assert(CODES['-'] === '010000101', '-')

  // 3) 宽度算术：每个字符恒为 6 窄 + 3 宽 = 15 单位；字间空 1
  //    "KQ-001" → 8 个字符（含首尾 *）→ 8*15 + 7*1 = 127
  const { svg, ratio } = code39Svg('KQ-001')
  assert(svg.includes('viewBox="0 0 127 '), `viewBox 宽度不对：${svg.slice(0, 80)}`)
  assert(ratio > 0 && ratio < 20, `宽高比异常 ${ratio}`)

  // 4) 反向解码：从 SVG 里的矩形几何还原文本。扫描枪就是干这个的，
  //    解得出原文才说明条与空的宽度关系是对的。
  const roundtrip = (text: string) => {
    const svg = code39Svg(text).svg
    const rects = [...svg.matchAll(/<rect x="([\d.]+)" y="0" width="([\d.]+)"/g)]
      .map((m) => ({ x: Number(m[1]), w: Number(m[2]) }))
    // 元素序列按 bar/space 交替还原：空宽 = 下一根条的 x − 当前条的右边缘
    const elems: number[] = []
    rects.forEach((r, i) => {
      elems.push(r.w)
      if (i < rects.length - 1) elems.push(Number((rects[i + 1].x - (r.x + r.w)).toFixed(3)))
    })
    const rev = new Map(Object.entries(CODES).map(([c, p]) => [p, c]))
    let out = ''
    for (let i = 0; i + 9 <= elems.length; i += 10) {
      const pat = elems.slice(i, i + 9).map((w) => (w === WIDE ? '1' : '0')).join('')
      const ch = rev.get(pat)
      assert(!!ch, `无法解码 pattern ${pat}`)
      out += ch
    }
    return out
  }
  for (const text of ['KQ-001', 'A3288', 'BOX20260127ABC123456', '0', 'Z-9']) {
    assert(roundtrip(text) === `*${text}*`, `${text} 解码结果不符：${roundtrip(text)}`)
  }

  // 5) 小写自动转大写；不支持的字符被 canEncode 拒掉
  assert(code39Svg('kq-001').svg === code39Svg('KQ-001').svg, '小写应自动转大写')
  assert(canEncode('KQ-001'), 'canEncode 误拒')
  assert(!canEncode('kq_001'), '下划线不在 Code 39 字符集')

  console.log('code39 self-check ok')
}

function escapeXml(s: string): string {
  return s.replace(/[<>&'"]/g, (c) => (
    { '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[c] as string
  ))
}
