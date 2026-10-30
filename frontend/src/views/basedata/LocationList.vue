<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { baseDataApi, LOCATION_STATUS, LOCATION_TYPES, type Location } from '@/api/basedata'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<Location[]>([])
const total = ref(0)
const warehouses = ref<{ id: number; name: string }[]>([])
const canManage = ref(false)

const query = reactive({ warehouse_id: undefined as number | undefined, code: '', type: '', status: '', page: 1, page_size: 20 })

const dialog = reactive({ visible: false, editing: 0, saving: false })
const form = reactive({
  code: '',
  name: '',
  type: 'NORMAL',
  warehouse_id: undefined as number | undefined,
  cap_pallet: 8,
  cap_material: 200,
  coord_x: undefined as number | undefined,
  coord_y: undefined as number | undefined,
  dist_to_dock: undefined as number | undefined,
  dist_to_pack: undefined as number | undefined,
})
const formRef = ref<FormInstance>()
const rules: FormRules = {
  code: [{ required: true, message: '请输入库位编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入库位名称', trigger: 'blur' }],
  warehouse_id: [{ required: true, message: '请选择所属仓库', trigger: 'change' }],
}

async function load() {
  loading.value = true
  try {
    const d = await baseDataApi.locations({
      warehouse_id: query.warehouse_id || undefined,
      code: query.code || undefined,
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
  return LOCATION_STATUS.find((x) => x.value === s)?.tag ?? 'info'
}
function statusLabel(s: string) {
  return LOCATION_STATUS.find((x) => x.value === s)?.label ?? s
}

function openCreate() {
  dialog.editing = 0
  Object.assign(form, {
    code: '', name: '', type: 'NORMAL',
    warehouse_id: query.warehouse_id, cap_pallet: 8, cap_material: 200,
    coord_x: undefined, coord_y: undefined, dist_to_dock: undefined, dist_to_pack: undefined,
  })
  dialog.visible = true
}
function openEdit(row: Location) {
  dialog.editing = row.id
  Object.assign(form, {
    code: row.code, name: row.name, type: row.type, warehouse_id: row.warehouse_id,
    cap_pallet: row.cap_pallet, cap_material: row.cap_material,
    coord_x: row.coord_x ?? undefined, coord_y: row.coord_y ?? undefined,
    dist_to_dock: undefined, dist_to_pack: undefined,
  })
  dialog.visible = true
}

async function save() {
  await formRef.value?.validate()
  dialog.saving = true
  try {
    if (dialog.editing) await baseDataApi.updateLocation(dialog.editing, { ...form })
    else await baseDataApi.createLocation({ ...form })
    ElMessage.success('已保存')
    dialog.visible = false
    load()
  } finally {
    dialog.saving = false
  }
}

async function setStatus(row: Location, status: string) {
  if (status === 'LOCKED') {
    await ElMessageBox.confirm(`锁定后该库位不能出入库，确认锁定「${row.code}」？`, '锁定确认', {
      type: 'warning',
    })
  }
  await baseDataApi.setLocationStatus(row.id, status)
  ElMessage.success('已更新')
  load()
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canManage.value = user.can('basedata:manage')
  warehouses.value = user.me?.warehouses ?? []
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">库位管理（P19）</h2>

    <div class="toolbar">
      <el-select v-model="query.warehouse_id" placeholder="所属仓库" clearable style="width: 170px" @change="load">
        <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
      </el-select>
      <el-input v-model="query.code" placeholder="库位编码" clearable style="width: 160px" @keyup.enter="load" />
      <el-select v-model="query.type" placeholder="库位类型" clearable style="width: 130px">
        <el-option v-for="t in LOCATION_TYPES" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 110px">
        <el-option v-for="s in LOCATION_STATUS" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button v-if="canManage" type="primary" @click="openCreate">新增库位</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="code" label="库位编码" width="120" class-name="mono" />
      <el-table-column prop="name" label="库位名称" min-width="140" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          {{ LOCATION_TYPES.find((t) => t.value === row.type)?.label ?? row.type }}
        </template>
      </el-table-column>
      <el-table-column prop="warehouse_name" label="所属仓库" min-width="130" />
      <el-table-column label="容量(托盘)" width="110" align="right">
        <template #default="{ row }">{{ row.used_pallet }} / {{ row.cap_pallet }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="坐标" width="150">
        <template #default="{ row }">
          <span v-if="!row.coord_missing" class="mono">({{ row.coord_x }}, {{ row.coord_y }})</span>
          <el-tag v-else type="danger" size="small">坐标缺失</el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="row.status !== 'LOCKED' && row.status !== 'MAINTAIN'"
            link
            type="warning"
            @click="setStatus(row, 'LOCKED')"
          >
            锁定
          </el-button>
          <el-button
            v-else
            link
            type="success"
            @click="setStatus(row, 'IDLE')"
          >
            解锁
          </el-button>
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

    <el-dialog v-model="dialog.visible" :title="dialog.editing ? '编辑库位' : '新增库位'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="库位编码" prop="code">
          <el-input v-model="form.code" placeholder="A1-01-01" maxlength="32" />
        </el-form-item>
        <el-form-item label="库位名称" prop="name">
          <el-input v-model="form.name" maxlength="64" />
        </el-form-item>
        <el-form-item label="所属仓库" prop="warehouse_id">
          <el-select v-model="form.warehouse_id" style="width: 100%">
            <el-option v-for="w in warehouses" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="库位类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option v-for="t in LOCATION_TYPES" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="容量">
          <div class="flex">
            <el-input-number v-model="form.cap_pallet" :min="0" controls-position="right" />
            <span class="muted">托盘</span>
            <el-input-number v-model="form.cap_material" :min="0" controls-position="right" />
            <span class="muted">物料</span>
          </div>
        </el-form-item>
        <el-form-item label="坐标">
          <div class="flex">
            <el-input-number v-model="form.coord_x" :precision="2" controls-position="right" />
            <el-input-number v-model="form.coord_y" :precision="2" controls-position="right" />
            <span class="muted">必填，缺失则不参与 AI 推荐（BR-025）</span>
          </div>
        </el-form-item>
        <el-form-item label="到装卸台(米)">
          <el-input-number v-model="form.dist_to_dock" :precision="2" :min="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="到打包台(米)">
          <el-input-number v-model="form.dist_to_pack" :precision="2" :min="0" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
