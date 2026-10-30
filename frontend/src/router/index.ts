import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue') },
      {
        path: 'basedata/warehouse',
        name: 'warehouse',
        component: () => import('@/views/basedata/WarehouseList.vue'),
        meta: { title: '仓库管理', perm: 'basedata:view' },
      },
      {
        path: 'basedata/location',
        name: 'location',
        component: () => import('@/views/basedata/LocationList.vue'),
        meta: { title: '库位管理', perm: 'basedata:view' },
      },
      {
        path: 'basedata/barcode',
        name: 'barcode',
        component: () => import('@/views/basedata/BarcodeList.vue'),
        meta: { title: '条码管理', perm: 'basedata:view' },
      },
      {
        path: 'system/user',
        name: 'user',
        component: () => import('@/views/system/UserList.vue'),
        meta: { title: '账号管理', perm: 'system:manage' },
      },
      {
        path: 'system/role',
        name: 'role',
        component: () => import('@/views/system/RoleMatrix.vue'),
        meta: { title: '角色与权限', perm: 'system:manage' },
      },
      {
        path: 'system/config',
        name: 'config',
        component: () => import('@/views/system/SysConfig.vue'),
        meta: { title: '规则配置', perm: 'system:manage' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  const user = useUserStore()
  if (to.meta.public) return true
  if (!user.token) return { path: '/login', query: { redirect: to.fullPath } }
  if (!user.me) {
    try {
      await user.loadMe()
    } catch {
      return { path: '/login' }
    }
  }
  const need = to.meta.perm as string | undefined
  if (need && !user.can(need)) {
    return { path: '/dashboard' }
  }
  return true
})

export default router
