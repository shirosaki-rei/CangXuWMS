/** 会话：token 与 API 地址持久化到 SecureStore，APP 重启不丢。 */
import * as SecureStore from 'expo-secure-store'
import { createContext, useContext } from 'react'
import { DEFAULT_API_BASE } from '../config'

const K_TOKEN = 'wms_token'
const K_BASE = 'wms_api_base'

export interface Session {
  token: string
  apiBase: string
  name: string
  role: string
  warehouses: { id: number; name: string }[]
}

export interface SessionState {
  session: Session | null
  ready: boolean
  signIn: (s: Session) => Promise<void>
  signOut: () => Promise<void>
  setApiBase: (base: string) => Promise<void>
}

export const SessionContext = createContext<SessionState | null>(null)

export function useSession(): SessionState {
  const c = useContext(SessionContext)
  if (!c) throw new Error('useSession 必须在 SessionContext 内使用')
  return c
}

export async function loadStored(): Promise<Session | null> {
  const token = await SecureStore.getItemAsync(K_TOKEN)
  if (!token) return null
  const apiBase = (await SecureStore.getItemAsync(K_BASE)) ?? DEFAULT_API_BASE
  const meta = await SecureStore.getItemAsync('wms_meta')
  const m = meta ? JSON.parse(meta) : {}
  return {
    token,
    apiBase,
    name: m.name ?? '',
    role: m.role ?? '',
    warehouses: m.warehouses ?? [],
  }
}

export async function saveSession(s: Session): Promise<void> {
  await SecureStore.setItemAsync(K_TOKEN, s.token)
  await SecureStore.setItemAsync(K_BASE, s.apiBase)
  await SecureStore.setItemAsync(
    'wms_meta',
    JSON.stringify({ name: s.name, role: s.role, warehouses: s.warehouses }),
  )
}

export async function clearSession(): Promise<void> {
  await SecureStore.deleteItemAsync(K_TOKEN)
  await SecureStore.deleteItemAsync('wms_meta')
}

export async function storedApiBase(): Promise<string> {
  return (await SecureStore.getItemAsync(K_BASE)) ?? DEFAULT_API_BASE
}

export async function persistApiBase(base: string): Promise<void> {
  await SecureStore.setItemAsync(K_BASE, base)
}
