/**
 * 错误码映射。来源：docs/WMS接口文档.md 1.2，与后端 app/core/errors.py 一一对应。
 * 后端 code 与 HTTP 状态分离：业务错误 HTTP 仍是 200，只有传输/认证层才用 4xx/5xx。
 */
export interface BizError {
  code: string
  message: string
  data?: unknown
  trace_id?: string
}

/** 展示给用户的处置提示（接口文档 1.2 的「前端处理」列） */
export const CODE_HINT: Record<string, string> = {
  'WMS-4001': '请检查表单填写',
  'WMS-4010': '登录已过期，请重新登录',
  'WMS-4011': '签名校验失败，请联系系统管理员',
  'WMS-4030': '没有权限执行该操作',
  'WMS-4091': '重复提交，已返回首次结果',
  'WMS-4092': '单据已关闭或已作废，请刷新列表',
  'WMS-4093': '编码已存在，请更换',
  'WMS-4094': '数据已被他人修改，请拉取最新后重试',
  'WMS-4221': '不满足业务规则',
  'WMS-4222': '可用库存不足，建议拆单',
  'WMS-4290': '操作过于频繁，请稍后重试',
  'WMS-5000': '服务端异常，请稍后重试',
}

/** 需要静默处理的业务码（幂等重放视为成功） */
export const SILENT_CODES = new Set(['WMS-4091'])

export function isBizError(e: unknown): e is BizError {
  return typeof e === 'object' && e !== null && 'code' in e && typeof (e as BizError).code === 'string'
}

/**
 * 这几种码后端的 message 对用户没意义（多是英文内部信息），固定用映射文案。
 */
const PREFER_HINT = new Set(['WMS-5000', 'WMS-4011'])

/**
 * 优先用后端给出的具体 message。
 *
 * 后端 BizError 的 message 是「用户名或密码错误」「密码连续错误已达上限，账号锁定中，
 * 请 7 分钟后重试」这类可操作信息；而 CODE_HINT 里 WMS-4221 只有一句「不满足业务规则」。
 * 若用映射覆盖，登录失败这类最需要诊断的场景反而只剩一句废话。
 * 所以映射表只作兜底：后端没给 message、或码属于 PREFER_HINT 时才用。
 */
export function messageOf(code: string, backendMessage?: string): string {
  const msg = (backendMessage ?? '').trim()
  if (msg && !PREFER_HINT.has(code)) return msg
  return CODE_HINT[code] ?? msg ?? '请求失败'
}
