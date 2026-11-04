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
        path: 'inventory/product',
        name: 'inventory-product',
        component: () => import('@/views/inventory/ProductStockList.vue'),
        meta: { title: '成品库存明细', perm: 'inventory:view' },
      },
      {
        path: 'inventory/material',
        name: 'inventory-material',
        component: () => import('@/views/inventory/MaterialStockList.vue'),
        meta: { title: '物料库存明细', perm: 'inventory:view' },
      },
      {
        path: 'txn/product',
        name: 'txn-product',
        component: () => import('@/views/inventory/TxnList.vue'),
        meta: { title: '产品出入库查询', perm: 'inventory:view' },
      },
      {
        path: 'txn/material',
        name: 'txn-material',
        component: () => import('@/views/inventory/TxnList.vue'),
        meta: { title: '物料出入库查询', perm: 'inventory:view' },
      },
      {
        path: 'inbound',
        name: 'inbound',
        component: () => import('@/views/inbound/InboundList.vue'),
        meta: { title: '入库管理', perm: 'inventory:view' },
      },
      {
        path: 'inbound/:id',
        name: 'inbound-detail',
        component: () => import('@/views/inbound/InboundDetail.vue'),
        meta: { title: '入库详情', perm: 'inventory:view' },
      },
      {
        path: 'inspection',
        name: 'inspection',
        component: () => import('@/views/inbound/InspectionList.vue'),
        meta: { title: '来料检验', perm: 'inventory:view' },
      },
      {
        path: 'outbound',
        name: 'outbound',
        component: () => import('@/views/outbound/OutboundList.vue'),
        meta: { title: '出库管理', perm: 'inventory:view' },
      },
      {
        path: 'outbound/:id',
        name: 'outbound-detail',
        component: () => import('@/views/outbound/OutboundDetail.vue'),
        meta: { title: '出库详情', perm: 'inventory:view' },
      },
      {
        path: 'stocktake',
        name: 'stocktake',
        component: () => import('@/views/stocktake/StocktakeList.vue'),
        meta: { title: '物料盘点', perm: 'inventory:view' },
      },
      {
        path: 'stocktake/:id',
        name: 'stocktake-detail',
        component: () => import('@/views/stocktake/StocktakeDetail.vue'),
        meta: { title: '盘点详情', perm: 'inventory:view' },
      },
      {
        path: 'move',
        name: 'move',
        component: () => import('@/views/stocktake/MoveList.vue'),
        meta: { title: '物料移位', perm: 'inventory:view' },
      },
      {
        path: 'basedata/supplier',
        name: 'supplier',
        component: () => import('@/views/basedata/SupplierList.vue'),
        meta: { title: '供应商档案', perm: 'inventory:view' },
      },
      {
        path: 'ai/query',
        name: 'ai-query',
        component: () => import('@/views/ai/QueryView.vue'),
        meta: { title: '智能问数', perm: 'ai:query' },
      },
      {
        path: 'ai/dashboard',
        name: 'ai-dashboard',
        component: () => import('@/views/ai/AiDashboard.vue'),
        meta: { title: 'AI 效果看板', perm: 'ai:dashboard' },
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
