<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { inventoryApi, type ProductStock } from '@/api/inventory'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const user = useUserStore()
const loading = ref(false)
const rows = ref<ProductStock[]>([])
const total = ref(0)
const query = reactive({ name: '', code: '', date_from: '', date_to: '', page: 1, page_size: 20 })

async function load() {
  loading.value = true
  try {
    const d = await inventoryApi.products({
      name: query.name || undefined,
      code: query.code || undefined,
      date_from: query.date_from || undefined,
      date_to: query.date_to || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = d.items
    total.value = d.total
  } finally {
    loading.value = false
  }
}

function drill(row: ProductStock) {
  router.push({ path: '/txn/product', query: { code: row.code, name: row.name } })
}

function exportCsv() {
  inventoryApi.exportCsv('inventory_products', {
    name: query.name || undefined,
    code: query.code || undefined,
    date_from: query.date_from || undefined,
    date_to: query.date_to || undefined,
  })
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">成品库存明细（P01）</h2>

    <div class="toolbar">
      <el-input v-model="query.name" placeholder="产品名称" clearable style="width: 170px" @keyup.enter="load" />
      <el-input v-model="query.code" placeholder="产品编码" clearable style="width: 150px" @keyup.enter="load" />
      <el-date-picker v-model="query.date_from" type="date" value-format="YYYY-MM-DD" placeholder="入库起始" style="width: 150px" />
      <el-date-picker v-model="query.date_to" type="date" value-format="YYYY-MM-DD" placeholder="入库截止" style="width: 150px" />
      <el-button type="primary" @click="load">查询</el-button>
      <el-button @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe @row-dblclick="drill">
      <el-table-column prop="code" label="产品编码" width="110" class-name="mono" />
      <el-table-column prop="name" label="产品名称" min-width="130" />
      <el-table-column label="规格型号" min-width="230">
        <template #default="{ row }">
          <div v-for="s in row.spec" :key="s" class="spec-line">{{ s }}</div>
        </template>
      </el-table-column>
      <el-table-column label="产品数量" width="110" align="right">
        <template #default="{ row }">
          <span :class="{ zero: row.zero }">{{ row.qty }}</span>
          <span class="unit">{{ row.unit }}</span>
        </template>
      </el-table-column>
      <el-table-column label="可用" width="90" align="right">
        <template #default="{ row }">{{ row.available }}</template>
      </el-table-column>
      <el-table-column label="最新入库日期" width="160">
        <template #default="{ row }">
          <span v-if="row.last_inbound_at">{{ new Date(row.last_inbound_at).toLocaleString('zh-CN', { hour12: false }) }}</span>
          <span v-else class="muted">—</span>
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
    <p class="muted mt8">双击行可下钻到该 SKU 的出入库流水</p>
  </div>
</template>

<style scoped>
.spec-line { line-height: 1.5; color: #555; font-size: 12px; }
.zero { color: #bbb; }
.unit { color: var(--muted); font-size: 12px; margin-left: 3px; }
</style>
