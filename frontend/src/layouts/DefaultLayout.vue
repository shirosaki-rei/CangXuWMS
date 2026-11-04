<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import BrandMark from '@/components/BrandMark.vue'

const router = useRouter()
const user = useUserStore()
const active = ref('dashboard')

interface MenuItem {
  path: string
  title: string
  perm?: string
}
interface MenuGroup {
  name: string
  items: MenuItem[]
}

const groups = computed<MenuGroup[]>(() => {
  const can = (p?: string) => !p || user.can(p)
  const out: MenuGroup[] = [
    { name: '工作台', items: [{ path: '/dashboard', title: '首页' }] },
    {
      name: '实时库存查询',
      items: [
        { path: '/inventory/product', title: '成品库存明细', perm: 'inventory:view' },
        { path: '/inventory/material', title: '物料库存明细', perm: 'inventory:view' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: '出入库查询',
      items: [
        { path: '/txn/product', title: '产品出入库查询', perm: 'inventory:view' },
        { path: '/txn/material', title: '物料出入库查询', perm: 'inventory:view' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: '入库管理',
      items: [
        { path: '/inbound', title: '入库单', perm: 'inventory:view' },
        { path: '/inspection', title: '来料检验', perm: 'inventory:view' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: '出库管理',
      items: [
        { path: '/outbound', title: '出库单', perm: 'inventory:view' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: '库内作业',
      items: [
        { path: '/stocktake', title: '物料盘点', perm: 'inventory:view' },
        { path: '/move', title: '物料移位', perm: 'inventory:view' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: 'AI 建议层',
      items: [
        { path: '/ai/dashboard', title: 'AI 效果看板', perm: 'ai:dashboard' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: '基础设置',
      items: [
        { path: '/basedata/warehouse', title: '仓库管理', perm: 'basedata:view' },
        { path: '/basedata/location', title: '库位管理', perm: 'basedata:view' },
        { path: '/basedata/barcode', title: '条码管理', perm: 'basedata:view' },
        { path: '/basedata/supplier', title: '供应商档案', perm: 'inventory:view' },
      ].filter((i) => can(i.perm)),
    },
    {
      name: '账号与权限',
      items: [
        { path: '/system/user', title: '账号管理', perm: 'system:manage' },
        { path: '/system/role', title: '角色与权限', perm: 'system:manage' },
        { path: '/system/config', title: '规则配置', perm: 'system:manage' },
      ].filter((i) => can(i.perm)),
    },
  ]
  return out.filter((g) => g.items.length)
})

const title = computed(() => {
  for (const g of groups.value) {
    const hit = g.items.find((i) => i.path === router.currentRoute.value.path)
    if (hit) return hit.title
  }
  return '首页'
})

function go(path: string) {
  active.value = path
  router.push(path)
}

async function onLogout() {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
  await user.logout()
  router.replace('/login')
}

// 顶栏当前路由高亮
router.afterEach((to) => { active.value = to.path })
</script>

<template>
  <div>
    <header class="topbar">
      <div class="logo"><BrandMark :size="22" /><span>仓序 WMS</span></div>
      <div class="spacer" />
      <span class="who">
        {{ user.me?.name }}（{{ user.me?.role_label }}）
      </span>
      <el-button link class="logout" @click="onLogout">退出</el-button>
    </header>

    <div class="crumb">首页 / {{ title }}</div>

    <div class="main">
      <aside class="side">
        <template v-for="g in groups" :key="g.name">
          <div class="grp">{{ g.name }}</div>
          <a v-for="i in g.items" :key="i.path" :class="{ on: active === i.path }" @click="go(i.path)">
            {{ i.title }}
          </a>
        </template>
      </aside>

      <main class="content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.logout { color: #fff; margin-left: 14px; font-size: 13px; }
</style>
