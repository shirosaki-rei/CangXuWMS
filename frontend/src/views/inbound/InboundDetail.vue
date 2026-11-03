<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { inboundApi, type InboundOrder } from '@/api/inbound'
import { baseDataApi, LOCATION_STATUS, type Location } from '@/api/basedata'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const orderId = Number(route.params.id)
const loading = ref(false)
const order = ref<InboundOrder | null>(null)
const locations = ref<Location[]>([])
const canVoid = ref(false)

const canExec = computed(() => !!user.me?.permissions.includes('inbound:exec'))
const canSubmit = computed(() => !!user.me?.permissions.includes('inbound:submit'))

async function load() {
  loading.value = true
  try {
    order.value = await inboundApi.detail(orderId)
    locations.value = await baseDataApi.locations({ page: 1, page_size: 100 }).then((d) => d.items)
  } finally {
    loading.value = false
  }
}

function statusTag(s?: string) {
  return s === 'DONE' ? 'success' : s === 'VOID' ? 'danger' : s === 'PARTIAL' ? 'warning' : 'info'
}

// ---------------------------------------------------------------- 扫码
const scanDlg = reactive({ visible: false, saving: false })
const scanForm = reactive({ box_code: '', sn: '', location_id: undefined as number | undefined, qty: 1 })
const scanRef = ref<FormInstance>()
const scanRules: FormRules = {
  location_id: [{ required: true, message: '必须扫库位码', trigger: 'change' }],
  qty: [{ required: true, type: 'number', min: 1, message: '数量至少 1', trigger: 'blur' }],
}

function openScan() {
  Object.assign(scanForm, { box_code: '', sn: '', location_id: undefined, qty: 1 })
  scanDlg.visible = true
}

async function doScan() {
  await scanRef.value?.validate()
  if (!scanForm.box_code && !scanForm.sn) {
    ElMessage.warning('箱码与 SN 至少要填一个')
    return
  }
  scanDlg.saving = true
  try {
    const r = await inboundApi.scan(orderId, { ...scanForm })
    ElMessage.success(`已收 ${r.scanned} / ${r.plan_qty}（${r.status}）`)
    scanDlg.visible = false
    load()
  } finally {
    scanDlg.saving = false
  }
}

// ---------------------------------------------------------------- 提交
const submitDlg = reactive({ visible: false, saving: false, reason: '' })
const needReason = computed(
  () => !!order.value && order.value.actual_qty !== order.value.plan_qty,
)

function openSubmit() {
  submitDlg.reason = ''
  submitDlg.visible = true
}

async function doSubmit() {
  if (needReason.value && submitDlg.reason.trim().length < 5) {
    ElMessage.warning('实收与计划不一致，差异原因至少 5 个字')
    return
  }
  submitDlg.saving = true
  try {
    await inboundApi.submit(orderId, submitDlg.reason.trim() || undefined)
    ElMessage.success('已提交入库')
    submitDlg.visible = false
    load()
  } finally {
    submitDlg.saving = false
  }
}

// ---------------------------------------------------------------- 作废
async function onVoid() {
  const { value } = await ElMessageBox.prompt('作废原因（必填，会留痕）', '作废入库单', {
    inputPlaceholder: '请填写作废原因',
    inputValidator: (v) => (v && v.trim().length >= 5) || '原因至少 5 个字',
  })
  await inboundApi.void(orderId, value.trim())
  ElMessage.success('已作废')
  load()
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canVoid.value = !!user.me?.permissions.includes('inbound:void')
  await load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="crumb-bar">
      <el-button link type="primary" @click="router.push('/inbound')">← 返回入库列表</el-button>
    </div>

    <template v-if="order">
      <div class="head">
        <h2 class="panel-title" style="margin: 0">
          入库详情（P09） · <span class="mono">{{ order.no }}</span>
        </h2>
        <div class="acts">
          <el-button v-if="canExec && !order.terminal" type="primary" @click="openScan">扫码收货</el-button>
          <el-button v-if="canSubmit && !order.terminal" type="primary" @click="openSubmit">
            提交入库
          </el-button>
          <el-button v-if="canVoid && !order.terminal" type="danger" @click="onVoid">作废</el-button>
        </div>
      </div>

      <div class="card">
        <h3 class="panel-title">基础信息</h3>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="入库单号">{{ order.no }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ order.type_label }}</el-descriptions-item>
          <el-descriptions-item label="来源单号">{{ order.source_no ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="单据状态">
            <el-tag :type="statusTag(order.status)" size="small">{{ order.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="计划数量">{{ order.plan_qty }}</el-descriptions-item>
          <el-descriptions-item label="实收数量">
            <span :class="{ warn: order.actual_qty !== order.plan_qty }">{{ order.actual_qty }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ order.created_at }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ order.finished_at ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ order.version }}</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="order.qty_mismatch" type="warning" :closable="false" class="mt8"
                  title="明细行累计数量与计划数不一致" show-icon />
      </div>

      <div class="card mt16">
        <h3 class="panel-title">箱内产品明细</h3>
        <el-table :data="order.items ?? []" border stripe>
          <el-table-column type="index" label="序号" width="60" />
          <el-table-column prop="sku_code" label="SKU 编码" width="150" class-name="mono" />
          <el-table-column prop="box_code" label="箱码" min-width="180" class-name="mono">
            <template #default="{ row }">{{ row.box_code ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="sn" label="SN 码" min-width="170" class-name="mono">
            <template #default="{ row }">{{ row.sn ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="上架库位" width="150">
            <template #default="{ row }">
              <span v-if="row.location_code" class="mono">{{ row.location_code }}</span>
              <el-tag v-else type="warning" size="small">未分配</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="qty" label="数量" width="90" align="right" />
        </el-table>
      </div>
    </template>

    <!-- 扫码收货 -->
    <el-dialog v-model="scanDlg.visible" title="扫码收货" width="460px">
      <el-form ref="scanRef" :model="scanForm" :rules="scanRules" label-width="80px">
        <el-form-item label="箱码">
          <el-input v-model="scanForm.box_code" placeholder="扫箱码，或填 SN" maxlength="64" />
        </el-form-item>
        <el-form-item label="SN 码">
          <el-input v-model="scanForm.sn" placeholder="逐件入库时填 SN" maxlength="64" />
        </el-form-item>
        <el-form-item label="上架库位" prop="location_id">
          <el-select v-model="scanForm.location_id" filterable style="width: 100%">
            <el-option v-for="l in locations" :key="l.id" :value="l.id"
                       :disabled="l.status === 'LOCKED' || l.status === 'MAINTAIN'">
              <span class="mono">{{ l.code }}</span>
              <span class="muted"> · {{ l.warehouse_name }} ·
                {{ LOCATION_STATUS.find((s) => s.value === l.status)?.label }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="数量" prop="qty">
          <el-input-number v-model="scanForm.qty" :min="1" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scanDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="scanDlg.saving" @click="doScan">确认收货</el-button>
      </template>
    </el-dialog>

    <!-- 提交入库 -->
    <el-dialog v-model="submitDlg.visible" title="提交入库" width="460px">
      <el-alert v-if="needReason" type="warning" :closable="false" class="mt8"
                :title="`实收 ${order?.actual_qty} 与计划 ${order?.plan_qty} 不一致，必须填写差异原因（≥5 字）`"
                show-icon />
      <el-form label-width="80px" class="mt16">
        <el-form-item label="差异原因">
          <el-input v-model="submitDlg.reason" type="textarea" :rows="3" maxlength="255"
                    placeholder="实收与计划一致时可不填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="submitDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitDlg.saving" @click="doSubmit">确认提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.crumb-bar { margin-bottom: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.acts { display: flex; gap: 8px; }
.warn { color: #e65c2e; font-weight: 600; }
</style>
