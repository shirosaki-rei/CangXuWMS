import { get } from './request'

export interface ProductStock {
  id: number
  code: string
  name: string
  spec: string[]
  qty: number
  locked: number
  frozen: number
  available: number
  unit: string
  last_inbound_at: string | null
  zero: boolean
}

export interface MaterialStock {
  id: number
  code: string
  name: string
  type: string
  unit: string
  qty: number
  locked: number
  frozen: number
  available: number
  in_transit: number
  safety_stock: number
  low_stock: boolean
}

export interface TxnRow {
  id: number
  sku_id: number
  sku_code: string
  sku_name: string
  sku_type: string
  location_id: number
  biz_type: string
  biz_type_label: string
  biz_no: string
  qty_delta: number
  balance: number
  created_at: string
}

export interface SkuSummary {
  sku_id: number
  sku_type: string
  code: string
  name: string
  qty: number
  locked: number
  frozen: number
  available: number
  locations: {
    location_id: number
    location_code: string
    qty: number
    locked: number
    frozen: number
    available: number
  }[]
}

export const BIZ_TYPES = [
  { value: 'PURCHASE_IN', label: '采购入库' },
  { value: 'PRODUCT_IN', label: '产品入库' },
  { value: 'RETURN_IN', label: '生产退料' },
  { value: 'GAIN_IN', label: '盘盈入库' },
  { value: 'SALES_OUT', label: '销售出库' },
  { value: 'PICK_OUT', label: '生产领料' },
  { value: 'LOSS_OUT', label: '盘亏出库' },
  { value: 'MOVE', label: '移位' },
  { value: 'VOID_REVERSE', label: '作废冲销' },
]

export const inventoryApi = {
  products: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: ProductStock[] }>(
      '/inventory/products',
      params,
    ),
  materials: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: MaterialStock[] }>(
      '/inventory/materials',
      params,
    ),
  txn: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: TxnRow[] }>('/txn', params),
  summary: (skuType: string, skuId: number) =>
    get<SkuSummary>('/txn/summary', { sku_type: skuType, sku_id: skuId }),
  /** 导出：直接让浏览器下载，返回 blob */
  exportCsv: (biz: string, params?: Record<string, any>) =>
    get(`/export/${biz}`, params, { responseType: 'blob' }),
}
