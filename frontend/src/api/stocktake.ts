import { get, post, put } from './request'

export interface Stocktake {
  id: number
  no: string
  type: string
  type_label: string
  mode: string
  mode_label: string
  warehouse_id: number
  warehouse_name: string | null
  status: string
  status_label: string
  total: number
  done: number
  undone: number
  diff_loss: number
  diff_gain: number
  operator_id: number
  created_at: string
  finished_at: string | null
  terminal?: boolean
}

export interface StocktakeItem {
  id: number
  material_id: number
  material_code: string
  material_name: string
  unit: string
  location_id: number
  location_code: string
  real_qty: number | null
  counted: boolean
  /** 盲盘时后端不返回这两个字段 */
  book_qty?: number
  diff?: number
}

export interface MoveOrder {
  id: number
  no: string
  material_id: number
  material_code: string | null
  material_name: string | null
  unit: string | null
  from_location_id: number
  from_location_code: string | null
  to_location_id: number
  to_location_code: string | null
  qty: number
  status: string
  status_label: string
  operator_id: number
  created_at: string
  finished_at: string | null
}

export interface Supplier {
  id: number
  code: string
  name: string
  over_receive: number | null
  contact: string | null
  status: string
}

export const STOCKTAKE_TYPES = [
  { value: 'FULL', label: '全盘' },
  { value: 'SPOT', label: '抽盘' },
  { value: 'CYCLE', label: '循环盘点' },
]

export const STOCKTAKE_STATUS = [
  { value: 'PENDING', label: '待盘点', tag: 'info' },
  { value: 'COUNTING', label: '盘点中', tag: 'warning' },
  { value: 'CONFIRMING', label: '待确认', tag: 'primary' },
  { value: 'DONE', label: '已完成', tag: 'success' },
  { value: 'CANCELED', label: '已取消', tag: 'danger' },
]

export const stocktakeApi = {
  list: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: Stocktake[] }>(
      '/stocktakes',
      params,
    ),
  create: (body: Record<string, any>) => post<Record<string, any>>('/stocktakes', body),
  detail: (id: number) => get<Stocktake>(`/stocktakes/${id}`),
  items: (id: number) => get<StocktakeItem[]>(`/stocktakes/${id}/items`),
  count: (id: number, body: { location_id: number; material_id: number; real_qty: number }) =>
    post<{ done: number; total: number; status: string }>(`/stocktakes/${id}/count`, body),
  submit: (id: number, note?: string) =>
    post<{ status: string; diff_loss: number; diff_gain: number; loss_no: string | null; gain_no: string | null }>(
      `/stocktakes/${id}/submit`,
      { note },
    ),
}

export const moveApi = {
  list: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: MoveOrder[] }>(
      '/move-orders',
      params,
    ),
  create: (body: { material_id: number; from_location_id: number; to_location_id: number; qty: number }) =>
    post<{ id: number; no: string; source_remain: number }>('/move-orders', body),
}

export const supplierApi = {
  list: (params?: Record<string, any>) => get<Supplier[]>('/suppliers', params),
  update: (id: number, body: Partial<Supplier>) => put(`/suppliers/${id}`, body),
}
