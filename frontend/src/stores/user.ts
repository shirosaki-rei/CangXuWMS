import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi, type Me } from '@/api/auth'

const TOKEN_KEY = 'wms_token'
const REFRESH_KEY = 'wms_refresh'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) ?? '')
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) ?? '')
  const me = ref<Me | null>(null)

  function setTokens(access: string, refresh: string) {
    token.value = access
    refreshToken.value = refresh
    localStorage.setItem(TOKEN_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  }

  async function loadMe() {
    if (!token.value) return null
    me.value = await authApi.me()
    return me.value
  }

  function reset() {
    token.value = ''
    refreshToken.value = ''
    me.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  }

  async function logout() {
    try {
      await authApi.logout()
    } finally {
      reset()
    }
  }

  /** 权限判断：与后端 app/core/permissions.py 的 MATRIX 对应 */
  function can(perm: string): boolean {
    return me.value?.permissions.includes(perm) ?? false
  }

  return { token, refreshToken, me, setTokens, loadMe, reset, logout, can }
})
