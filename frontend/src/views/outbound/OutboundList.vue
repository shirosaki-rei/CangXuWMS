<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { OUTBOUND_STATUS, OUTBOUND_TYPES, outboundApi, type OutboundOrder } from '@/api/outbound'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const user = useUserStore()
const loading = ref(false)
const rows = ref<OutboundOrder[]>([])
const total = ref(0)
const counts = ref<Record<string, Record<string, number>>>({})
const query = reactive({ type: '', status: '', no: '', source_no: '', page: 1, page_size: 20 })

async function load() {
  loading.value = true
  try {
    const [d, c] = await Promise.all([
      outboundApi.list({
        type: query.type || undefined,
        status: query.status || undefined,
        no: query.no || undefined,
        source_no: query.source_no || undefined,
        page: query.page,
        page_size: query.page_size,
      }),
      outboundApi.counts(),
    ])
    rows.value = d.items
    total.value = d.total
    counts.value = c
  } finally {
    loading.value = false
  }
}

function statusTag(s: string) {
  return OUTBOUND_STATUS.find((x) => x.value === s)?.tag ?? 'info'
}

function open(row: OutboundOrder) {
  router.push(`/outbound/${row.id}`)
}

function onTab(t: string) {
  query.type = t
  query.page = 1
  load()
}

function countOf(type: string) {
  const c = counts.value[type]
  return c ? Object.values(c).reduce((a, b) => a + b, 0) : 0
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">出库管理</h2>

    <el-tabs :model-value="query.type" @tab-change="onTab">
      <el-tab-pane :label="`全部（${total}）`" name="" />
      <el-tab-pane v-for="t in OUTBOUND_TYPES" :key="t.value"
                   :label="`${t.label}（${countOf(t.value)}）`" :name="t.value" />
    </el-tabs>

    <div class="toolbar">
      <el-input v-model="query.no" placeholder="出库单号" clearable style="width: 180px" @keyup.enter="load" />
      <el-input v-model="query.source_no" placeholder="来源单号（销售订单/领料需求）" clearable
                style="width: 230px" @keyup.enter="load" />
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px">
        <el-option v-for="s in OUTBOUND_STATUS" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe @row-dblclick="open">
      <el-table-column prop="no" label="出库单号" width="160" class-name="mono" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ row.type_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source_no" label="来源单号" width="150" class-name="mono">
        <template #default="{ row }">{{ row.source_no ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="计划 / 实发" width="120" align="right">
        <template #default="{ row }">
          <span :class="{ warn: row.actual_qty !== row.plan_qty }">
            {{ row.actual_qty }} / {{ row.plan_qty }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="165" />
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="open(row)">出库详情</el-button>
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
  </div>
</template>

<style scoped>
.warn { color: #e65c2e; font-weight: 600; }
</style>
