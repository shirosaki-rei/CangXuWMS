<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { moveApi, type MoveOrder } from '@/api/stocktake'
import { baseDataApi, type Location } from '@/api/basedata'
import { get } from '@/api/request'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<MoveOrder[]>([])
const total = ref(0)
const locations = ref<Location[]>([])
const materials = ref<{ id: number; code: string; name: string; unit: string }[]>([])
const query = reactive({ no: '', page: 1, page_size: 20 })

const dlg = reactive({
  visible: false, saving: false,
  material_id: undefined as number | undefined,
  from_location_id: undefined as number | undefined,
  to_location_id: undefined as number | undefined,
  qty: 1,
})

async function load() {
  loading.value = true
  try {
    const [d, mats] = await Promise.all([
      moveApi.list({ no: query.no || undefined, page: query.page, page_size: query.page_size }),
      get<{ items: any[] }>('/inventory/materials', { page: 1, page_size: 100 }),
    ])
    rows.value = d.items
    total.value = d.total
    materials.value = mats.items.map((m) => ({
      id: m.id, code: m.code, name: m.name, unit: m.unit,
    }))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(dlg, {
    visible: true, material_id: undefined, from_location_id: undefined,
    to_location_id: undefined, qty: 1,
  })
}

async function create() {
  const { material_id, from_location_id, to_location_id, qty } = dlg
  if (!material_id || !from_location_id || !to_location_id) {
    ElMessage.warning('物料与两个库位都必须选')
    return
  }
  if (from_location_id === to_location_id) {
    ElMessage.warning('移入库位不能与移出库位相同')
    return
  }
  dlg.saving = true
  try {
    const r = await moveApi.create({
      material_id, from_location_id, to_location_id, qty,
    })
    ElMessage.success(`移位单 ${r.no} 已完成，源库位剩余 ${r.source_remain}`)
    dlg.visible = false
    await load()
  } finally {
    dlg.saving = false
  }
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  locations.value = await baseDataApi.locations({ page: 1, page_size: 100 }).then((d) => d.items)
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">物料移位（P17）</h2>
    <p class="muted" style="margin-bottom: 10px">
      移位不改总量，只改库位维度；移空后源库位自动回「空闲」。APP 侧是「扫源库位 → 扫物料 → 扫目标库位」三扫。
    </p>

    <div class="toolbar">
      <el-input v-model="query.no" placeholder="移库单号" clearable style="width: 180px" @keyup.enter="load" />
      <el-button type="primary" @click="load">查询</el-button>
      <el-button type="primary" @click="openCreate">发起移位</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="no" label="移库单号" width="160" class-name="mono" />
      <el-table-column label="物料" min-width="180">
        <template #default="{ row }">
          <div>{{ row.material_name }}</div>
          <div class="muted mono">{{ row.material_code }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="from_location_code" label="移出库位" width="130" class-name="mono" />
      <el-table-column prop="to_location_code" label="移入库位" width="130" class-name="mono" />
      <el-table-column label="数量" width="90" align="right">
        <template #default="{ row }">{{ row.qty }} {{ row.unit }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'DONE' ? 'success' : 'info'" size="small">
            {{ row.status_label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="时间" width="165" />
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

    <el-dialog v-model="dlg.visible" title="发起移位" width="460px">
      <el-form label-width="90px">
        <el-form-item label="物料">
          <el-select v-model="dlg.material_id" filterable style="width: 100%">
            <el-option v-for="m in materials" :key="m.id" :value="m.id"
                       :label="`${m.code} · ${m.name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="移出库位">
          <el-select v-model="dlg.from_location_id" filterable style="width: 100%">
            <el-option v-for="l in locations" :key="l.id" :value="l.id"
                       :label="`${l.code} · ${l.warehouse_name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="移入库位">
          <el-select v-model="dlg.to_location_id" filterable style="width: 100%">
            <el-option v-for="l in locations" :key="l.id" :value="l.id"
                       :label="`${l.code} · ${l.warehouse_name}`"
                       :disabled="l.status === 'LOCKED' || l.status === 'MAINTAIN'" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="dlg.qty" :min="1" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="create">确认移位</el-button>
      </template>
    </el-dialog>
  </div>
</template>
