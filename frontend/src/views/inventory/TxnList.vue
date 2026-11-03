<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { BIZ_TYPES, inventoryApi, type TxnRow } from '@/api/inventory'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const user = useUserStore()
const loading = ref(false)
const rows = ref<TxnRow[]>([])
const total = ref(0)
const skuType = ref<'PRODUCT' | 'MATERIAL'>((route.path.includes('material') ? 'MATERIAL' : 'PRODUCT'))
const title = skuType.value === 'PRODUCT' ? '产品出入库查询（P03）' : '物料出入库查询（P04）'

const query = reactive({
  code: (route.query.code as string) || '',
  name: (route.query.name as string) || '',
  biz_type: '',
  // 默认近 30 天（PRD 6.3.1）
  date_from: new Date(Date.now() - 30 * 86400_000).toISOString().slice(0, 10),
  date_to: new Date().toISOString().slice(0, 10),
  page: 1,
  page_size: 20,
})

async function load() {
  loading.value = true
  try {
    const d = await inventoryApi.txn({
      sku_type: skuType.value,
      code: query.code || undefined,
      name: query.name || undefined,
      biz_type: query.biz_type || undefined,
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

const summary = ref<{ qty: number; available: number; code: string; name: string } | null>(null)

async function drill(row: TxnRow) {
  summary.value = await inventoryApi.summary(row.sku_type, row.sku_id)
}

function exportCsv() {
  inventoryApi.exportCsv('txn', {
    sku_type: skuType.value,
    code: query.code || undefined,
    name: query.name || undefined,
    biz_type: query.biz_type || undefined,
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
    <h2 class="panel-title">{{ title }}</h2>

    <div class="toolbar">
      <el-input v-model="query.name" :placeholder="skuType === 'PRODUCT' ? '产品名称' : '物料名称'"
                clearable style="width: 170px" @keyup.enter="load" />
      <el-input v-model="query.code" placeholder="编码" clearable style="width: 160px" @keyup.enter="load" />
      <el-select v-model="query.biz_type" placeholder="业务类型" clearable style="width: 140px">
        <el-option v-for="b in BIZ_TYPES" :key="b.value" :label="b.label" :value="b.value" />
      </el-select>
      <el-date-picker v-model="query.date_from" type="date" value-format="YYYY-MM-DD" placeholder="起始" style="width: 145px" />
      <el-date-picker v-model="query.date_to" type="date" value-format="YYYY-MM-DD" placeholder="截止" style="width: 145px" />
      <el-button type="primary" @click="load">查询</el-button>
      <el-button @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe @row-dblclick="drill">
      <el-table-column prop="sku_code" label="编码" width="170" class-name="mono" />
      <el-table-column prop="sku_name" label="名称" min-width="140" />
      <el-table-column prop="biz_no" label="业务单据" width="150" class-name="mono" />
      <el-table-column label="业务类型" width="100">
        <template #default="{ row }">
          <el-tag :type="row.qty_delta > 0 ? 'success' : 'danger'" size="small" effect="plain">
            {{ row.biz_type_label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="数量" width="100" align="right">
        <template #default="{ row }">
          <span :class="row.qty_delta > 0 ? 'pos' : 'neg'">
            {{ row.qty_delta > 0 ? '+' : '' }}{{ row.qty_delta }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="balance" label="结存" width="90" align="right" />
      <el-table-column label="时间" width="165">
        <template #default="{ row }">
          {{ new Date(row.created_at).toLocaleString('zh-CN', { hour12: false }) }}
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

    <el-dialog v-model="summary" title="SKU 库存汇总" width="460px" @closed="summary = null">
      <template v-if="summary">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="编码">{{ summary.code }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ summary.name }}</el-descriptions-item>
          <el-descriptions-item label="总库存">{{ summary.qty }}</el-descriptions-item>
          <el-descriptions-item label="可用">{{ summary.available }}</el-descriptions-item>
        </el-descriptions>
        <p class="muted mt8">流水只增不改，不可删除；导出上限 5 万行。</p>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.pos { color: #18a058; font-weight: 600; }
.neg { color: #d03050; font-weight: 600; }
</style>
