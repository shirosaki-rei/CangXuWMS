<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { baseDataApi, WAREHOUSE_TYPES, type Warehouse } from '@/api/basedata'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<Warehouse[]>([])
const query = reactive({ name: '', type: '', status: '' })
const canManage = ref(false)

const dialog = reactive({ visible: false, editing: 0, saving: false })
const form = reactive({ code: '', name: '', type: 'MATERIAL', owner_id: undefined as number | undefined })
const formRef = ref<FormInstance>()
const rules: FormRules = {
  code: [{ required: true, message: '请输入仓库编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入仓库名称', trigger: 'blur' }],
  type: [{ required: true, message: '请选择仓库类型', trigger: 'change' }],
}

async function load() {
  loading.value = true
  try {
    rows.value = await baseDataApi.warehouses({
      name: query.name || undefined,
      type: query.type || undefined,
      status: query.status || undefined,
    })
  } finally {
    loading.value = false
  }
}

function typeTag(t: string) {
  return WAREHOUSE_TYPES.find((x) => x.value === t)?.tag ?? 'info'
}
function typeLabel(t: string) {
  return WAREHOUSE_TYPES.find((x) => x.value === t)?.label ?? t
}

function openCreate() {
  dialog.editing = 0
  Object.assign(form, { code: '', name: '', type: 'MATERIAL', owner_id: undefined })
  dialog.visible = true
}
function openEdit(row: Warehouse) {
  dialog.editing = row.id
  Object.assign(form, {
    code: row.code,
    name: row.name,
    type: row.type,
    owner_id: row.owner_id ?? undefined,
  })
  dialog.visible = true
}

async function save() {
  await formRef.value?.validate()
  dialog.saving = true
  try {
    if (dialog.editing) await baseDataApi.updateWarehouse(dialog.editing, { ...form })
    else await baseDataApi.createWarehouse({ ...form })
    ElMessage.success('已保存')
    dialog.visible = false
    load()
  } finally {
    dialog.saving = false
  }
}

async function toggle(row: Warehouse) {
  const next = row.status === 'ENABLED' ? 'DISABLED' : 'ENABLED'
  if (next === 'DISABLED') {
    const { blockers } = await baseDataApi.blockers(row.id)
    if (blockers.length) {
      await ElMessageBox.alert(
        blockers.map((b) => `· ${b}`).join('<br/>'),
        '该仓库不能停用（BR-014）',
        { type: 'warning', dangerouslyUseHTMLString: true },
      )
      return
    }
    await ElMessageBox.confirm(`确认停用「${row.name}」？停用后不再参与新业务。`, '停用确认', {
      type: 'warning',
    })
  }
  await baseDataApi.toggleWarehouse(row.id, next)
  ElMessage.success(next === 'ENABLED' ? '已启用' : '已停用')
  load()
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canManage.value = user.can('basedata:manage')
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">仓库管理（P18）</h2>

    <div class="toolbar">
      <el-input v-model="query.name" placeholder="仓库名称" clearable style="width: 180px" @keyup.enter="load" />
      <el-select v-model="query.type" placeholder="仓库类型" clearable style="width: 150px">
        <el-option v-for="t in WAREHOUSE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px">
        <el-option label="启用" value="ENABLED" />
        <el-option label="停用" value="DISABLED" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button v-if="canManage" type="primary" @click="openCreate">新增仓库</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="code" label="仓库编码" width="110" />
      <el-table-column prop="name" label="仓库名称" min-width="150" />
      <el-table-column label="仓库类型" width="110">
        <template #default="{ row }">
          <el-tag :type="typeTag(row.type)" size="small">{{ typeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="location_count" label="库位数量" width="100" align="right" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-switch
            :model-value="row.status === 'ENABLED'"
            :disabled="!canManage"
            @change="toggle(row)"
          />
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog.visible" :title="dialog.editing ? '编辑仓库' : '新增仓库'" width="460px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="仓库编码" prop="code">
          <el-input v-model="form.code" placeholder="WH-001" maxlength="32" />
        </el-form-item>
        <el-form-item label="仓库名称" prop="name">
          <el-input v-model="form.name" placeholder="1#原料仓" maxlength="64" />
        </el-form-item>
        <el-form-item label="仓库类型" prop="type">
          <el-select v-model="form.type" style="width: 100%">
            <el-option v-for="t in WAREHOUSE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人 ID">
          <el-input-number v-model="form.owner_id" :min="0" controls-position="right" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
