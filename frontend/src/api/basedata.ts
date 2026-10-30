import { get, post, put } from './request'

export interface Warehouse {
  id: number
  code: string
  name: string
  type: string
  status: string
  owner_id: number | null
  location_count: number
  created_at: string
}

export interface Location {
  id: number
  code: string
  name: string
  type: string
  warehouse_id: number
  warehouse_name: string
  cap_pallet: number
  cap_material: number
  used_pallet: number
  status: string
  coord_x: number | null
  coord_y: number | null
  coord_missing: boolean
  created_at: string
}

export interface Barcode {
  id: number
  code: string
  type: string
  ref_id: number | null
  created_at: string
}

export const WAREHOUSE_TYPES = [
  { value: 'MATERIAL', label: '原料', tag: 'primary' },
  { value: 'PRODUCT', label: '成品', tag: 'success' },
  { value: 'AUX', label: '辅料', tag: 'warning' },
  { value: 'SLOW', label: '呆滞', tag: 'danger' },
]

export const LOCATION_TYPES = [
  { value: 'NORMAL', label: '普通' },
  { value: 'STEREO', label: '立体' },
  { value: 'CONSTANT_TEMP', label: '恒温' },
  { value: 'DANGEROUS', label: '危品' },
]

export const LOCATION_STATUS = [
  { value: 'IDLE', label: '空闲', tag: 'info' },
  { value: 'OCCUPIED', label: '占用', tag: 'success' },
  { value: 'LOCKED', label: '锁定', tag: 'warning' },
  { value: 'MAINTAIN', label: '维保', tag: 'danger' },
]

export const BARCODE_TYPES = [
  { value: 'ZONE', label: '库区' },
  { value: 'LOCATION', label: '库位' },
  { value: 'MATERIAL', label: '物料' },
  { value: 'BOX', label: '箱码' },
]

export const baseDataApi = {
  warehouses: (params?: Record<string, any>) => get<Warehouse[]>('/warehouses', params),
  createWarehouse: (body: Partial<Warehouse>) => post<{ id: number }>('/warehouses', body),
  updateWarehouse: (id: number, body: Partial<Warehouse>) => put(`/warehouses/${id}`, body),
  toggleWarehouse: (id: number, status: string) =>
    post(`/warehouses/${id}/toggle`, { status }),
  blockers: (id: number) => get<{ blockers: string[] }>(`/warehouses/${id}/blockers`),

  locations: (params?: Record<string, any>) =>
    get<{ total: number; page: number; page_size: number; items: Location[] }>(
      '/locations',
      params,
    ),
  createLocation: (body: Partial<Location>) => post<{ id: number }>('/locations', body),
  updateLocation: (id: number, body: Partial<Location>) => put(`/locations/${id}`, body),
  setLocationStatus: (id: number, status: string) =>
    post(`/locations/${id}/status`, { status }),

  barcodes: (params?: Record<string, any>) => get<Barcode[]>('/barcodes', params),
  createBarcode: (body: Partial<Barcode>) => post<{ id: number }>('/barcodes', body),
  printBarcodes: (body: { ids: number[]; spec: string; copies: number }) =>
    post<{ total: number; items: { code: string }[] }>('/barcodes/print', body),
}
