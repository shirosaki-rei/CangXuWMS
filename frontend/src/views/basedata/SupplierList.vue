<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { supplierApi, type Supplier } from '@/api/stocktake'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<Supplier[]>([])
const query = reactive({ code: '', name: '' })
const canEdit = ref(false)

const dlg = reactive({
  visible: false, saving: false,
  id: 0, code: '', name: '',
  over_receive: null as number | null,
  contact: '',
  useOverride: false,
})

async function load() {
  loading.value = true
  try {
    rows.value = await supplierApi.list({
      code: query.code || undefined,
      name: query.name || undefined,
    })
  } finally {
    loading.value = false
  }
}

function openEdit(s: Supplier) {
  Object.assign(dlg, {
    visible: true,
    id: s.id,
    code: s.code,
    name: s.name,
    over_receive: s.over_receive,
    contact: s.contact ?? '',
    useOverride: s.over_receive !== null,
  })
}

async function save() {
  dlg.saving = true
  try {
    await supplierApi.update(dlg.id, {
      name: dlg.name,
      contact: dlg.contact || undefined,
      // 取消勾选时显式传 null，表示回落到全局默认（BR-023）
      over_receive: dlg.useOverride ? (dlg.over_receive ?? 0) : null,
    })
    ElMessage.success('已保存')
    dlg.visible = false
    await load()
  } finally {
    dlg.saving = false
  }
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canEdit.value = !!user.me?.permissions.includes('supplier:manage')
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">供应商档案</h2>
    <p class="muted" style="margin-bottom: 10px">
      超收阈值：留空表示使用全局默认（5%），填写则覆盖全局值（BR-023，覆盖值优先）。
    </p>

    <div class="toolbar">
      <el-input v-model="query.code" placeholder="供应商编码" clearable style="width: 180px" @keyup.enter="load" />
      <el-input v-model="query.name" placeholder="供应商名称" clearable style="width: 200px" @keyup.enter="load" />
      <el-button type="primary" @click="load">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="code" label="编码" width="150" class-name="mono" />
      <el-table-column prop="name" label="名称" min-width="220" />
      <el-table-column label="超收阈值" width="140" align="right">
        <template #default="{ row }">
          <el-tag v-if="row.over_receive !== null" size="small" type="warning">
            {{ (row.over_receive * 100).toFixed(0) }}%
          </el-tag>
          <span v-else class="muted">全局默认</span>
        </template>
      </el-table-column>
      <el-table-column prop="contact" label="联系方式" width="170">
        <template #default="{ row }">{{ row.contact ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ENABLED' ? 'success' : 'info'" size="small">
            {{ row.status === 'ENABLED' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canEdit" label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dlg.visible" :title="`编辑供应商 · ${dlg.code}`" width="460px">
      <el-form label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="dlg.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="联系方式">
          <el-input v-model="dlg.contact" maxlength="64" />
        </el-form-item>
        <el-form-item label="超收阈值">
          <el-checkbox v-model="dlg.useOverride" style="margin-bottom: 8px">
            覆盖全局默认
          </el-checkbox>
          <el-input-number
            v-if="dlg.useOverride"
            v-model="dlg.over_receive as number"
            :min="0" :max="1" :step="0.01" :precision="2"
            controls-position="right"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
