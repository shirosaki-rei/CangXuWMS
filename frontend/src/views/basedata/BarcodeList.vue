<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { baseDataApi, BARCODE_TYPES, type Barcode } from '@/api/basedata'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<Barcode[]>([])
const selected = ref<Barcode[]>([])
const canManage = ref(false)
const query = reactive({ code: '', type: '' })

const dialog = reactive({ visible: false, saving: false })
const form = reactive({ code: '', type: 'LOCATION', ref_id: undefined as number | undefined })
const formRef = ref<FormInstance>()
const rules: FormRules = {
  code: [{ required: true, message: '请输入条码', trigger: 'blur' }],
  type: [{ required: true, message: '请选择类型', trigger: 'change' }],
}

const printDlg = reactive({ visible: false, spec: '40x30', copies: 1, result: '' })

async function load() {
  loading.value = true
  try {
    rows.value = await baseDataApi.barcodes({
      code: query.code || undefined,
      type: query.type || undefined,
    })
  } finally {
    loading.value = false
  }
}

function typeLabel(t: string) {
  return BARCODE_TYPES.find((x) => x.value === t)?.label ?? t
}

function openCreate() {
  Object.assign(form, { code: '', type: 'LOCATION', ref_id: undefined })
  dialog.visible = true
}

async function save() {
  await formRef.value?.validate()
  dialog.saving = true
  try {
    await baseDataApi.createBarcode({ ...form })
    ElMessage.success('条码已生成')
    dialog.visible = false
    load()
  } finally {
    dialog.saving = false
  }
}

function openPrint() {
  if (!selected.value.length) {
    ElMessage.warning('请先勾选要打印的条码')
    return
  }
  printDlg.result = ''
  printDlg.spec = '40x30'
  printDlg.copies = 1
  printDlg.visible = true
}

async function doPrint() {
  const r = await baseDataApi.printBarcodes({
    ids: selected.value.map((b) => b.id),
    spec: printDlg.spec,
    copies: printDlg.copies,
  })
  printDlg.result = `已提交 ${r.total} 张（${printDlg.spec === '40x30' ? '40×30mm' : '60×40mm'} × ${printDlg.copies} 份）`
  ElMessage.success('已生成打印任务')
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canManage.value = user.can('basedata:manage')
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">条码管理（P20）</h2>

    <div class="toolbar">
      <el-input v-model="query.code" placeholder="条码" clearable style="width: 180px" @keyup.enter="load" />
      <el-select v-model="query.type" placeholder="条码类型" clearable style="width: 150px">
        <el-option v-for="t in BARCODE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <template v-if="canManage">
        <el-button type="primary" @click="openCreate">新增条码</el-button>
        <el-button @click="openPrint">批量打印</el-button>
      </template>
    </div>

    <el-table
      v-loading="loading"
      :data="rows"
      border
      stripe
      @selection-change="(s: Barcode[]) => (selected = s)"
    >
      <el-table-column v-if="canManage" type="selection" width="44" />
      <el-table-column prop="code" label="条码" min-width="160" class-name="mono" />
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ typeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ref_id" label="关联 ID" width="100" align="right">
        <template #default="{ row }">{{ row.ref_id ?? '—' }}</template>
      </el-table-column>
      <el-table-column prop="created_at" label="生成时间" width="170" />
    </el-table>

    <el-dialog v-model="dialog.visible" title="新增条码" width="420px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="条码" prop="code">
          <el-input v-model="form.code" placeholder="KQ-001" maxlength="64" />
        </el-form-item>
        <el-form-item label="类型" prop="type">
          <el-select v-model="form.type" style="width: 100%">
            <el-option v-for="t in BARCODE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联 ID">
          <el-input-number v-model="form.ref_id" :min="0" controls-position="right" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="printDlg.visible" title="批量打印条码" width="420px">
      <p class="muted">已选 {{ selected.length }} 个条码</p>
      <el-form label-width="80px" class="mt8">
        <el-form-item label="规格">
          <el-radio-group v-model="printDlg.spec">
            <el-radio value="40x30">40×30 mm</el-radio>
            <el-radio value="60x40">60×40 mm</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="份数">
          <el-input-number v-model="printDlg.copies" :min="1" :max="100" />
        </el-form-item>
      </el-form>
      <p v-if="printDlg.result" class="mono">{{ printDlg.result }}</p>
      <template #footer>
        <el-button @click="printDlg.visible = false">关闭</el-button>
        <el-button type="primary" @click="doPrint">生成打印任务</el-button>
      </template>
    </el-dialog>
  </div>
</template>
