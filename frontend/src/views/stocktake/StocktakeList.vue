<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { STOCKTAKE_STATUS, STOCKTAKE_TYPES, stocktakeApi, type Stocktake } from '@/api/stocktake'
import { baseDataApi, type Warehouse } from '@/api/basedata'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const user = useUserStore()
const loading = ref(false)
const rows = ref<Stocktake[]>([])
const total = ref(0)
const warehouses = ref<Warehouse[]>([])
const canCreate = ref(false)
const query = reactive({ no: '', type: '', status: '', page: 1, page_size: 20 })

const dlg = reactive({ visible: false, saving: false, warehouse_id: undefined as number | undefined, type: 'FULL', mode: 'BLIND' })

async function load() {
  loading.value = true
  try {
    const d = await stocktakeApi.list({
      no: query.no || undefined,
      type: query.type || undefined,
      status: query.status || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = d.items
    total.value = d.total
  } finally {
    loading.value = false
  }
}

function statusTag(s: string) {
  return STOCKTAKE_STATUS.find((x) => x.value === s)?.tag ?? 'info'
}

function openCreate() {
  Object.assign(dlg, { warehouse_id: warehouses.value[0]?.id, type: 'FULL', mode: 'BLIND' })
  dlg.visible = true
}

async function create() {
  if (!dlg.warehouse_id) {
    ElMessage.warning('请选择盘点仓库')
    return
  }
  dlg.saving = true
  try {
    const r = await stocktakeApi.create({
      warehouse_id: dlg.warehouse_id,
      type: dlg.type,
      mode: dlg.mode,
    })
    ElMessage.success(`已创建 ${r.no}（${r.total} 个条目），库位已锁定`)
    dlg.visible = false
    await load()
    router.push(`/stocktake/${r.id}`)
  } finally {
    dlg.saving = false
  }
}

function open(row: Stocktake) {
  router.push(`/stocktake/${row.id}`)
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canCreate.value = !!user.me?.permissions.includes('stocktake:manage')
  warehouses.value = await baseDataApi.warehouses()
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">物料盘点（P15）</h2>

    <div class="toolbar">
      <el-input v-model="query.no" placeholder="盘点单号" clearable style="width: 180px" @keyup.enter="load" />
      <el-select v-model="query.type" placeholder="盘点类型" clearable style="width: 130px">
        <el-option v-for="t in STOCKTAKE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px">
        <el-option v-for="s in STOCKTAKE_STATUS" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button v-if="canCreate" type="primary" @click="openCreate">新增盘点单</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe @row-dblclick="open">
      <el-table-column prop="no" label="盘点单号" width="160" class-name="mono" />
      <el-table-column prop="type_label" label="类型" width="100" />
      <el-table-column label="盘点方式" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.mode === 'BLIND' ? 'warning' : 'info'" effect="plain">
            {{ row.mode_label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="warehouse_name" label="盘点仓库" min-width="120" />
      <el-table-column label="全部 / 已盘 / 未盘" width="150" align="right">
        <template #default="{ row }">
          {{ row.total }} / {{ row.done }} /
          <span :class="{ warn: row.undone > 0 }">{{ row.undone }}</span>
        </template>
      </el-table-column>
      <el-table-column label="盘亏 / 盘盈" width="110" align="right">
        <template #default="{ row }">
          <span class="loss">{{ row.diff_loss }}</span> /
          <span class="gain">{{ row.diff_gain }}</span>
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
          <el-button link type="primary" @click="open(row)">盘点详情</el-button>
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

    <el-dialog v-model="dlg.visible" title="新增盘点单" width="460px">
      <el-alert type="warning" :closable="false" show-icon class="mb12"
                title="创建即锁定该仓库库位，盘点期间该仓不可出入库（BR-007）" />
      <el-form label-width="90px">
        <el-form-item label="盘点仓库">
          <el-select v-model="dlg.warehouse_id" style="width: 100%">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="盘点类型">
          <el-select v-model="dlg.type" style="width: 100%">
            <el-option v-for="t in STOCKTAKE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="盘点方式">
          <el-radio-group v-model="dlg.mode">
            <el-radio value="BLIND">盲盘（账面不可见）</el-radio>
            <el-radio value="OPEN">明盘</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <p class="muted">方式创建后不可改（BR-024）。生产默认盲盘。</p>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="create">创建并锁定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.warn { color: #e65c2e; font-weight: 600; }
.loss { color: #d03050; font-weight: 600; }
.gain { color: #18a058; font-weight: 600; }
.mb12 { margin-bottom: 12px; }
</style>
