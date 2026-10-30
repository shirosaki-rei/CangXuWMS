import { get, post, put } from './request'

export interface UserRow {
  id: number
  username: string
  name: string
  phone: string | null
  role: string
  role_label: string
  status: string
  warehouse_ids: number[]
  created_at: string
}

export interface RoleRow {
  value: string
  label: string
  permissions: string[]
}

export interface SysConfig {
  id: number
  cfg_key: string
  cfg_value: string
  value_type: string
  scope: string
  scope_id: number | null
  remark: string | null
  updated_at: string
}

export interface MatrixRow {
  key: string
  name: string
  KEEPER: string
  INSPECTOR: string
  SUPERVISOR: string
  ADMIN: string
}

export const ROLES = [
  { value: 'KEEPER', label: '仓管员' },
  { value: 'INSPECTOR', label: '检验员' },
  { value: 'SUPERVISOR', label: '仓库主管' },
  { value: 'ADMIN', label: '系统管理员' },
  { value: 'INTEGRATION', label: '集成账号' },
]

export const systemApi = {
  users: (params?: Record<string, any>) => get<UserRow[]>('/users', params),
  createUser: (body: Record<string, any>) => post<{ id: number }>('/users', body),
  updateUser: (id: number, body: Record<string, any>) => put(`/users/${id}`, body),
  assignRoles: (id: number, body: { role: string; warehouse_ids: number[] }) =>
    post(`/users/${id}/roles`, body),

  roles: () => get<RoleRow[]>('/roles'),
  matrix: () => get<{ rows: MatrixRow[]; roles: [string, string][] }>('/permission-matrix'),

  configs: (params?: Record<string, any>) => get<SysConfig[]>('/sys-configs', params),
  upsertConfig: (body: Partial<SysConfig>) => put('/sys-configs', body),
}
