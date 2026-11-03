import { get, post } from './request'

export interface InboundItem {
  id: number
  sku_id: number
  box_code: string | null
  sn: string | null
  qty: number
  location_id: number | null
  location_code?: string
  sku_code?: string
}

export interface InboundOrder {
  id: number
  no: string
  type: string
  type_label: string
  source_no: string | null
  supplier_id: number | null
  status: string
  status_label: string
  plan_qty: number
  actual_qty: number
  creator_id: number
  checker_id: number | null
  created_at: string
  finished_at: string | null
  version: number
  terminal: boolean
  box_code?: string | null
  location_id?: number | null
  items?: InboundItem[]
  qty_mismatch?: boolean
}

export interface InspectionItem {
  id: number
  material_id: number
  material_code: string
  material_name: string
  unit: string
  plan_qty: number
  actual_qty: number
  barcode: string | null
  qualified: boolean | null
}

export interface Inspection {
  id: number
  no: string
  supplier_id: number
  supplier_name: string | null
  logistics_no: string | null
  plate_no: string | null
  status: string
  status_label: string
  result: string | null
  result_label: string | null
  plan_qty: number
  actual_qty: number
  fail_reason: string | null
  creator_id: number
  created_at: string
  checked_at: string | null
  terminal: boolean
  items?: InspectionItem[]
  over_receive_ratio?: string
}

export const INBOUND_TYPES = [
  { value: 'PRODUCT', label: '产品入库' },
  { value: 'PURCHASE', label: '采购入库' },
  { value: 'RETURN', label: '生产退料' },
  { value: 'GAIN', label: '盘盈入库' },
]

export const INBOUND_STATUS = [
  { value: 'PENDING', label: '待入库', tag: 'info' },
  { value: 'PARTIAL', label: '部分入库', tag: 'warning' },
  { value: 'DONE', label: '已入库', tag: 'success' },
  { value: 'VOID', label: '已作废', tag: 'danger' },
]

export const INSPECTION_STATUS = [
  { value: 'PENDING', label: '待检', tag: 'info' },
  { value: 'CHECKING', label: '检验中', tag: 'warning' },
  { value: 'DONE', label: '已检', tag: 'success' },
]

export const INSPECTION_RESULTS = [
  { value: 'PASS', label: '合格' },
  { value: 'PARTIAL', label: '部分合格' },
  { value: 'OVER_PASS', label: '合格（超收）' },
  { value: 'FAIL', label: '不合格' },
]

export const inboundApi = {
  list: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: InboundOrder[] }>(
      '/inbound-orders',
      params,
    ),
  counts: () => get<Record<string, Record<string, number>>>('/inbound-orders/status-counts'),
  detail: (id: number) => get<InboundOrder>(`/inbound-orders/${id}`),
  scan: (id: number, body: Record<string, any>) =>
    post<{ order_id: number; status: string; scanned: number; plan_qty: number }>(
      `/inbound-orders/${id}/scan`,
      body,
    ),
  submit: (id: number, reason?: string) =>
    post<{ order_id: number; no: string; status: string; actual_qty: number }>(
      `/inbound-orders/${id}/submit`,
      { reason },
    ),
  void: (id: number, reason: string) =>
    post<{ order_id: number; no: string; status: string }>(`/inbound-orders/${id}/void`, { reason }),
}

export const inspectionApi = {
  list: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: Inspection[] }>(
      '/inspections',
      params,
    ),
  detail: (id: number) => get<Inspection>(`/inspections/${id}`),
  scan: (id: number, body: Record<string, any>) =>
    post<{ inspection_id: number; status: string; scanned: number; plan_qty: number }>(
      `/inspections/${id}/scan`,
      body,
    ),
  judge: (id: number, body: { result: string; fail_reason?: string }) =>
    post<{ inspection_id: number; no: string; status: string; result: string; result_label: string }>(
      `/inspections/${id}/judge`,
      body,
    ),
  genInbound: (id: number, qty?: number) =>
    post<{ order_id: number; no: string; type: string; plan_qty: number; remain: number }>(
      `/inspections/${id}/gen-inbound`,
      { qty },
    ),
}
