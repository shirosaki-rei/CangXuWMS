<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { inventoryApi, type MaterialStock } from '@/api/inventory'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const user = useUserStore()
const loading = ref(false)
const rows = ref<MaterialStock[]>([])
const total = ref(0)
const query = reactive({ name: '', code: '', page: 1, page_size: 20 })
// 前端过滤：物料几百条，不值得为它加一个后端参数
const onlyLow = ref(false)

async function load() {
  loading.value = true
  try {
    const d = await inventoryApi.materials({
      name: query.name || undefined,
      code: query.code || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = onlyLow.value ? d.items.filter((i) => i.low_stock) : d.items
    total.value = d.total
  } finally {
    loading.value = false
  }
}

function drill(row: MaterialStock) {
  router.push({ path: '/txn/material', query: { code: row.code, name: row.name } })
}

/** 低库存整行标黄（PRD 6.2.2） */
function rowClass({ row }: { row: MaterialStock }) {
  return row.low_stock ? 'low-stock-row' : ''
}

function exportCsv() {
  inventoryApi.exportCsv('inventory_materials', {
    name: query.name || undefined,
    code: query.code || undefined,
  })
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">物料库存明细（P02）</h2>

    <div class="toolbar">
      <el-input v-model="query.name" placeholder="物料名称" clearable style="width: 180px" @keyup.enter="load" />
      <el-input v-model="query.code" placeholder="物料编码" clearable style="width: 200px" @keyup.enter="load" />
      <el-button type="primary" @click="load">查询</el-button>
      <el-button @click="exportCsv">导出 CSV</el-button>
      <el-checkbox v-model="onlyLow" @change="load">只看低库存</el-checkbox>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe @row-dblclick="drill"
              :row-class-name="rowClass">
      <el-table-column prop="code" label="物料编码" width="190" class-name="mono" />
      <el-table-column prop="name" label="物料名称" min-width="170" />
      <el-table-column prop="type" label="类型" width="80" />
      <el-table-column label="总库存" width="90" align="right">
        <template #default="{ row }">{{ row.qty }} {{ row.unit }}</template>
      </el-table-column>
      <el-table-column label="可用库存" width="100" align="right">
        <template #default="{ row }">
          <span :class="{ warn: row.low_stock }">{{ row.available }}</span>
        </template>
      </el-table-column>
      <el-table-column label="在途" width="80" align="right">
        <template #default="{ row }">{{ row.in_transit || '—' }}</template>
      </el-table-column>
      <el-table-column label="安全库存" width="90" align="right">
        <template #default="{ row }">{{ row.safety_stock }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.low_stock" type="warning" size="small">低库存</el-tag>
          <span v-else class="muted">正常</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="drill(row)">流水</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="mt8"
      v-model:current-page="query.page"
      v-model:page-size="query.page_size"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      background
      @current-change="load"
      @size-change="load"
    />
    <p class="muted mt8">可用库存 = 总库存 − 锁库 − 冻结；低于安全库存整行标黄</p>
  </div>
</template>
<style scoped>
.warn { color: #e65c2e; font-weight: 600; }
:deep(.low-stock-row) { background: #fffbe6; }
:deep(.low-stock-row:hover > td) { background: #fff3c4 !important; }
</style>
