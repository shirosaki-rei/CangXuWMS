<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import { INSPECTION_RESULTS, INSPECTION_STATUS, inspectionApi, type Inspection } from '@/api/inbound'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const rows = ref<Inspection[]>([])
const total = ref(0)
const detail = ref<Inspection | null>(null)
/** 扫码对话框的物料下拉：用来料单自己的明细，不额外加接口 */
const scanMaterials = ref<{ id: number; code: string; name: string; unit: string }[]>([])
const query = reactive({ no: '', status: '', result: '', page: 1, page_size: 20 })

const canJudge = computed(() => !!user.me?.permissions.includes('inspection:judge'))

async function load() {
  loading.value = true
  try {
    const d = await inspectionApi.list({
      no: query.no || undefined,
      status: query.status || undefined,
      result: query.result || undefined,
      page: query.page,
      page_size: query.page_size,
    })
    rows.value = d.items
    total.value = d.total
  } finally {
    loading.value = false
  }
}

function statusTag(s?: string) {
  return INSPECTION_STATUS.find((x) => x.value === s)?.tag ?? 'info'
}
function resultTag(r?: string | null) {
  return r === 'PASS' ? 'success' : r === 'FAIL' ? 'danger' : r ? 'warning' : 'info'
}

// ---------------------------------------------------------------- 扫码
const scanDlg = reactive({ visible: false, saving: false, inspectionId: 0 })
const scanForm = reactive({ material_id: undefined as number | undefined, barcode: '', actual_qty: 1 })
const scanRef = ref<FormInstance>()

async function openScan(row: Inspection) {
  scanDlg.inspectionId = row.id
  Object.assign(scanForm, { material_id: undefined, barcode: '', actual_qty: 1 })
  // 拉详情拿物料明细，顺带把最新实收数带进来
  detail.value = await inspectionApi.detail(row.id)
  scanMaterials.value = (detail.value?.items ?? []).map((i) => ({
    id: i.material_id, code: i.material_code, name: i.material_name, unit: i.unit,
  }))
  scanDlg.visible = true
}

async function doScan() {
  if (!scanForm.material_id) {
    ElMessage.warning('请选择物料')
    return
  }
  scanDlg.saving = true
  try {
    const r = await inspectionApi.scan(scanDlg.inspectionId, { ...scanForm })
    ElMessage.success(`已收 ${r.scanned} / ${r.plan_qty}`)
    scanDlg.visible = false
    load()
  } finally {
    scanDlg.saving = false
  }
}

// ---------------------------------------------------------------- 判定
const judgeDlg = reactive({ visible: false, saving: false, inspectionId: 0, no: '', result: 'PASS', fail_reason: '' })

function openJudge(row: Inspection) {
  Object.assign(judgeDlg, {
    visible: true,
    inspectionId: row.id,
    no: row.no,
    result: 'PASS',
    fail_reason: '',
  })
}

async function doJudge() {
  if (judgeDlg.result === 'FAIL' && !judgeDlg.fail_reason.trim()) {
    ElMessage.warning('判定为不合格必须填写原因')
    return
  }
  judgeDlg.saving = true
  try {
    await inspectionApi.judge(judgeDlg.inspectionId, {
      result: judgeDlg.result,
      fail_reason: judgeDlg.fail_reason.trim() || undefined,
    })
    ElMessage.success('判定已提交')
    judgeDlg.visible = false
    load()
  } finally {
    judgeDlg.saving = false
  }
}

// ---------------------------------------------------------------- 生成入库单
async function onGenInbound(row: Inspection) {
  const { value } = await ElMessageBox.prompt(
    `本次入库数量（剩余合格 ${row.actual_qty}，留空取全部）`,
    '生成采购入库单',
    { inputPlaceholder: '数量', inputType: 'number' },
  )
  const r = await inspectionApi.genInbound(row.id, value ? Number(value) : undefined)
  ElMessage.success(`已生成入库单 ${r.no}（剩余 ${r.remain}）`)
  load()
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  load()
})
</script>

<template>
  <div>
    <h2 class="panel-title">来料检验（P14）</h2>

    <div class="toolbar">
      <el-input v-model="query.no" placeholder="检验单号" clearable style="width: 180px" @keyup.enter="load" />
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px">
        <el-option v-for="s in INSPECTION_STATUS" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-select v-model="query.result" placeholder="判定结果" clearable style="width: 140px">
        <el-option v-for="r in INSPECTION_RESULTS" :key="r.value" :label="r.label" :value="r.value" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe>
      <el-table-column prop="no" label="检验单号" width="160" class-name="mono" />
      <el-table-column prop="supplier_name" label="供应商" min-width="200" show-overflow-tooltip />
      <el-table-column prop="logistics_no" label="物流单号" width="150" class-name="mono">
        <template #default="{ row }">{{ row.logistics_no ?? '—' }}</template>
      </el-table-column>
      <el-table-column prop="plate_no" label="车牌号" width="100">
        <template #default="{ row }">{{ row.plate_no ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="计划 / 实收" width="110" align="right">
        <template #default="{ row }">
          <span :class="{ warn: row.actual_qty !== row.plan_qty }">
            {{ row.actual_qty }} / {{ row.plan_qty }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="判定" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.result" :type="resultTag(row.result)" size="small">
            {{ row.result_label }}
          </el-tag>
          <span v-else class="muted">未判定</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="165" />
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canJudge && !row.terminal" link type="primary" @click="openScan(row)">
            扫码
          </el-button>
          <el-button v-if="canJudge && !row.terminal" link type="primary" @click="openJudge(row)">
            判定
          </el-button>
          <el-button
            v-if="row.status === 'DONE' && row.result && row.result !== 'FAIL'"
            link
            type="success"
            @click="onGenInbound(row)"
          >
            生成入库单
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

    <el-dialog v-model="scanDlg.visible" title="来料检验扫码" width="440px">
      <el-form ref="scanRef" label-width="80px">
        <el-form-item label="物料">
          <el-select v-model="scanForm.material_id" filterable style="width: 100%">
            <el-option v-for="m in scanMaterials" :key="m.id" :value="m.id"
                       :label="`${m.code} · ${m.name}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="条码">
          <el-input v-model="scanForm.barcode" maxlength="64" />
        </el-form-item>
        <el-form-item label="实收数量">
          <el-input-number v-model="scanForm.actual_qty" :min="1" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scanDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="scanDlg.saving" @click="doScan">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="judgeDlg.visible" :title="`检验判定 · ${judgeDlg.no}`" width="440px">
      <el-form label-width="90px">
        <el-form-item label="判定结果">
          <el-radio-group v-model="judgeDlg.result">
            <el-radio v-for="r in INSPECTION_RESULTS" :key="r.value" :value="r.value">
              {{ r.label }}
            </el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="不合格原因">
          <el-input v-model="judgeDlg.fail_reason" type="textarea" :rows="2" maxlength="255"
                    placeholder="判定为不合格时必填，进供应商质量档案" />
        </el-form-item>
      </el-form>
      <p class="muted">超收阈值按供应商档案覆盖值优先，否则用全局默认 5%。</p>
      <template #footer>
        <el-button @click="judgeDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="judgeDlg.saving" @click="doJudge">提交判定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.warn { color: #e65c2e; font-weight: 600; }
</style>
