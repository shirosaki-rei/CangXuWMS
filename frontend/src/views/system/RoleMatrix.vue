<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { systemApi, type MatrixRow, type RoleRow } from '@/api/system'

const loading = ref(false)
const roles = ref<RoleRow[]>([])
const rows = ref<MatrixRow[]>([])

const COLUMNS: { key: keyof MatrixRow; label: string }[] = [
  { key: 'KEEPER', label: '仓管员' },
  { key: 'INSPECTOR', label: '检验员' },
  { key: 'SUPERVISOR', label: '仓库主管' },
  { key: 'ADMIN', label: '系统管理员' },
]

async function load() {
  loading.value = true
  try {
    const [r, m] = await Promise.all([systemApi.roles(), systemApi.matrix()])
    roles.value = r
    rows.value = m.rows
  } finally {
    loading.value = false
  }
}

function cellType(v: string): 'success' | 'info' | 'warning' {
  if (v === '✅') return 'success'
  if (v === '—') return 'info'
  return 'warning'
}

onMounted(load)
</script>

<template>
  <div>
    <h2 class="panel-title">角色与权限矩阵（PRD 3.2）</h2>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="name" label="功能" min-width="230" fixed />
      <el-table-column v-for="c in COLUMNS" :key="String(c.key)" :label="c.label" width="120" align="center">
        <template #default="{ row }">
          <el-tag :type="cellType(row[c.key])" size="small" effect="plain">{{ row[c.key] }}</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <h2 class="panel-title mt16">角色明细</h2>
    <el-table :data="roles" border>
      <el-table-column prop="label" label="角色" width="120" />
      <el-table-column prop="value" label="编码" width="140" class-name="mono" />
      <el-table-column label="已授权功能">
        <template #default="{ row }">
          <el-tag v-for="p in row.permissions" :key="p" size="small" class="perm">{{ p }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.perm { margin: 2px 5px 2px 0; font-family: Consolas, Menlo, monospace; }
</style>
