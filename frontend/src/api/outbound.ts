import { get, post } from './request'

export interface OutboundOrder {
  id: number
  no: string
  type: string
  type_label: string
  source_no: string | null
  status: string
  status_label: string
  plan_qty: number
  actual_qty: number
  creator_id: number
  created_at: string
  finished_at: string | null
  version: number
  terminal: boolean
  items?: OutboundItem[]
  row_violations?: number[]
}

export interface OutboundItem {
  id: number
  sku_id: number
  sn: string | null
  location_id: number | null
  location_code?: string
  sku_code?: string
  status: string
  operator_id: number | null
  operated_at: string
}

export interface FifiLocation {
  location_id: number
  location_code: string
  available: number
  first_in_at: string
  take_qty?: number
}

export const OUTBOUND_TYPES = [
  { value: 'SALES', label: '销售出库' },
  { value: 'PICK', label: '领料出库' },
  { value: 'LOSS', label: '盘亏出库' },
]

export const OUTBOUND_STATUS = [
  { value: 'PENDING', label: '待出库', tag: 'info' },
  { value: 'PARTIAL', label: '部分出库', tag: 'warning' },
  { value: 'DONE', label: '已出库', tag: 'success' },
  { value: 'VOID', label: '已作废', tag: 'danger' },
]

export const ITEM_STATUS = [
  { value: 'PENDING', label: '待出库', tag: 'info' },
  { value: 'PICKED', label: '已拣货', tag: 'warning' },
  { value: 'SHIPPED', label: '已发货', tag: 'success' },
]

export const outboundApi = {
  list: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: OutboundOrder[] }>(
      '/outbound-orders',
      params,
    ),
  counts: () => get<Record<string, Record<string, number>>>('/outbound-orders/status-counts'),
  detail: (id: number) => get<OutboundOrder>(`/outbound-orders/${id}`),
  fifo: (id: number) =>
    get<{ sku_id: number; plan_qty: number; shortage: number; fifo: boolean; locations: FifiLocation[] }>(
      `/outbound-orders/${id}/fifo`,
    ),
  pick: (id: number, body: { location_id: number; qty: number; sn?: string }) =>
    post<{ order_id: number; status: string; picked: number; plan_qty: number; remain: number }>(
      `/outbound-orders/${id}/pick`,
      body,
    ),
  submit: (id: number, reason?: string) =>
    post<{ order_id: number; no: string; status: string; actual_qty: number; remain: number }>(
      `/outbound-orders/${id}/submit`,
      { reason },
    ),
  void: (id: number, reason: string) =>
    post<{ order_id: number; no: string; status: string }>(`/outbound-orders/${id}/void`, {
      reason,
    }),
}
