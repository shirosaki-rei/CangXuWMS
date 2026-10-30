import { get, post } from './request'

export interface Captcha {
  captcha_id: string
  image: string
  ttl: number
}

export interface LoginResult {
  access_token: string
  expires_in: number
  refresh_token: string
  user: { id: number; name: string; role: string; warehouses: { id: number; name: string }[] }
  landing: string
}

export interface Me {
  id: number
  username: string
  name: string
  phone?: string
  role: string
  role_label: string
  permissions: string[]
  warehouses: { id: number; name: string }[]
}

export const authApi = {
  captcha: () => get<Captcha>('/auth/captcha'),
  login: (body: { username: string; password: string; captcha_id: string; captcha: string }) =>
    post<LoginResult>('/auth/login', body),
  logout: () => post('/auth/logout', {}),
  me: () => get<Me>('/auth/me'),
}
