<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { baseDataApi, BARCODE_TYPES, type Barcode } from '@/api/basedata'
import { useUserStore } from '@/stores/user'
import { canEncode, code39Svg } from '@/utils/code39'

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

const printDlg = reactive({ visible: false, spec: '40x30', copies: 1 })

/** 打印预览：每张标签一组 {code, svg}，copies 展开 */
const labels = ref<{ code: string; svg: string }[]>([])
const SPEC_MM: Record<string, [number, number]> = { '40x30': [40, 30], '60x40': [60, 40] }

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
  printDlg.spec = '40x30'
  printDlg.copies = 1
  buildLabels()
  printDlg.visible = true
}

/** 条码在本地渲染成 SVG，打印走浏览器 → 系统打印机驱动，不依赖服务端出图 */
function buildLabels() {
  const out: { code: string; svg: string }[] = []
  const bad: string[] = []
  for (const b of selected.value) {
    if (!canEncode(b.code)) {
      bad.push(b.code)
      continue
    }
    const { svg } = code39Svg(b.code)
    for (let i = 0; i < printDlg.copies; i++) out.push({ code: b.code, svg })
  }
  labels.value = out
  if (bad.length) {
    ElMessage.warning(`以下条码含 Code 39 不支持的字符，已跳过：${bad.join('、')}`)
  }
}

/** 把 @page 尺寸按规格注入，再调浏览器打印 */
function doPrint() {
  if (!labels.value.length) {
    ElMessage.warning('没有可打印的标签')
    return
  }
  const [w, h] = SPEC_MM[printDlg.spec]
  const styleId = 'label-page-style'
  document.getElementById(styleId)?.remove()
  const style = document.createElement('style')
  style.id = styleId
  style.textContent = `@page { size: ${w}mm ${h}mm; margin: 0; }`
  document.head.appendChild(style)
  window.print()
}

watch(() => [printDlg.spec, printDlg.copies], buildLabels)

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

    <el-dialog v-model="printDlg.visible" title="批量打印条码" width="560px">
      <el-form label-width="80px" inline>
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

      <p class="muted">
        预览：{{ selected.length }} 个条码 × {{ printDlg.copies }} 份 = {{ labels.length }} 张
      </p>
      <div class="label-sheet">
        <div v-for="(l, i) in labels" :key="i" class="label" :class="'p-' + printDlg.spec">
          <div class="label-barcode" v-html="l.svg" />
        </div>
      </div>
      <p class="muted mt8">
        浏览器打印会调起系统打印对话框；请选标签打印机，并把纸张设为
        {{ SPEC_MM[printDlg.spec][0] }}×{{ SPEC_MM[printDlg.spec][1] }} mm、边距设为「无」。
      </p>
      <template #footer>
        <el-button @click="printDlg.visible = false">关闭</el-button>
        <el-button type="primary" @click="doPrint">打印（{{ labels.length }} 张）</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style>
.label-sheet {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 320px;
  overflow: auto;
  padding: 8px;
  background: #f4f7fb;
  border: 1px solid #e5e5e5;
}
.label {
  background: #fff;
  border: 1px dashed #c8d3e0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3mm 2mm;
}
.label.p-40x30 { width: 40mm; height: 30mm; }
.label.p-60x40 { width: 60mm; height: 40mm; }
.label-barcode { width: 100%; height: 100%; }

/* 打印时只留标签；一页一张，页面尺寸由 doPrint 注入的 @page 决定 */
@media print {
  body * { visibility: hidden; }
  .label-sheet, .label-sheet * { visibility: visible; }
  .label-sheet {
    position: absolute;
    left: 0;
    top: 0;
    max-height: none;
    overflow: visible;
    background: #fff;
    border: 0;
    padding: 0;
    gap: 0;
    display: block;
  }
  .label {
    border: 0;
    padding: 0;
    break-after: page;
    page-break-after: always;
  }
}
</style>
