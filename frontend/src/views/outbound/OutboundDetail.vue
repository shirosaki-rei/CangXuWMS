<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { ITEM_STATUS, outboundApi, type FifiLocation, type OutboundOrder } from '@/api/outbound'
import { baseDataApi, LOCATION_STATUS, type Location } from '@/api/basedata'
import { useUserStore } from '@/stores/user'
import CheckDialog from '@/components/CheckDialog.vue'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const orderId = Number(route.params.id)
const loading = ref(false)
const order = ref<OutboundOrder | null>(null)
const locations = ref<Location[]>([])
const fifo = ref<FifiLocation[]>([])
const fifoShortage = ref(0)
const canVoid = ref(false)
const checkRef = ref<InstanceType<typeof CheckDialog>>()

const canExec = computed(() => !!user.me?.permissions.includes('outbound:exec'))
const canSubmit = computed(() => !!user.me?.permissions.includes('outbound:submit'))

async function load() {
  loading.value = true
  try {
    order.value = await outboundApi.detail(orderId)
    locations.value = await baseDataApi.locations({ page: 1, page_size: 100 }).then((d) => d.items)
    await loadFifo()
  } finally {
    loading.value = false
  }
}

async function loadFifo() {
  try {
    const d = await outboundApi.fifo(orderId)
    fifo.value = d.locations
    fifoShortage.value = d.shortage
  } catch {
    // 没有明细的单（理论上不会）就不显示推荐
    fifo.value = []
  }
}

function statusTag(s?: string) {
  return s === 'DONE' ? 'success' : s === 'VOID' ? 'danger' : s === 'PARTIAL' ? 'warning' : 'info'
}
function itemTag(s: string) {
  return ITEM_STATUS.find((x) => x.value === s)?.tag ?? 'info'
}

// ---------------------------------------------------------------- 拣货
const pickDlg = reactive({ visible: false, saving: false })
const pickForm = reactive({ location_id: undefined as number | undefined, qty: 1, sn: '' })
const pickRef = ref<FormInstance>()
const pickRules: FormRules = {
  location_id: [{ required: true, message: '必须选发货库位', trigger: 'change' }],
  qty: [{ required: true, type: 'number', min: 1, message: '数量至少 1', trigger: 'blur' }],
}

function openPick() {
  Object.assign(pickForm, { location_id: undefined, qty: 1, sn: '' })
  pickDlg.visible = true
}

async function doPick() {
  await pickRef.value?.validate()
  pickDlg.saving = true
  try {
    const body: { location_id: number; qty: number; sn?: string } = {
      location_id: pickForm.location_id as number,
      qty: pickForm.qty,
    }
    if (pickForm.sn) body.sn = pickForm.sn
    const r = await outboundApi.pick(orderId, body)
    ElMessage.success(`已拣 ${r.picked} / ${r.plan_qty}，剩余 ${r.remain}`)
    pickDlg.visible = false
    await load()
  } finally {
    pickDlg.saving = false
  }
}

function useFifo(loc: FifiLocation) {
  pickForm.location_id = loc.location_id
  pickForm.qty = Math.min(loc.take_qty ?? loc.available, 1)
  pickDlg.visible = true
}

// ---------------------------------------------------------------- 提交
function openSubmit() {
  // 先跑 X04；可用库存不足等阻断项会让提交按钮置灰（BR-017）
  checkRef.value?.open('OUTBOUND', orderId, async (reason?: string) => {
    const r = await outboundApi.submit(orderId, reason)
    ElMessage.success(r.status === 'DONE' ? '已出库' : `已发 ${r.actual_qty}，剩余 ${r.remain} 可拆单继续发`)
    await load()
  })
}

// ---------------------------------------------------------------- 作废
async function onVoid() {
  const { value } = await ElMessageBox.prompt('作废原因（必填，会留痕）', '作出库单', {
    inputPlaceholder: '请填写作废原因',
    inputValidator: (v) => (v && v.trim().length >= 5) || '原因至少 5 个字',
  })
  await outboundApi.void(orderId, value.trim())
  ElMessage.success('已作废')
  await load()
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canVoid.value = !!user.me?.permissions.includes('outbound:void')
  await load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="crumb-bar">
      <el-button link type="primary" @click="router.push('/outbound')">← 返回出库列表</el-button>
    </div>

    <template v-if="order">
      <div class="head">
        <h2 class="panel-title" style="margin: 0">
          出库详情（P13） · <span class="mono">{{ order.no }}</span>
        </h2>
        <div class="acts">
          <el-button v-if="canExec && !order.terminal" type="primary" @click="openPick">扫码拣货</el-button>
          <el-button v-if="canSubmit && !order.terminal" type="primary" @click="openSubmit">
            提交出库
          </el-button>
          <el-button v-if="canVoid && !order.terminal" type="danger" @click="onVoid">作废</el-button>
        </div>
      </div>

      <div class="card">
        <h3 class="panel-title">基础信息</h3>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="出库单号">{{ order.no }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ order.type_label }}</el-descriptions-item>
          <el-descriptions-item label="来源单号">{{ order.source_no ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="单据状态">
            <el-tag :type="statusTag(order.status)" size="small">{{ order.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="计划数量">{{ order.plan_qty }}</el-descriptions-item>
          <el-descriptions-item label="实际出库">
            <span :class="{ warn: order.actual_qty !== order.plan_qty }">{{ order.actual_qty }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ order.created_at }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ order.finished_at ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ order.version }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- FIFO 推荐（BR-003） -->
      <div v-if="fifo.length || fifoShortage > 0" class="card mt16">
        <h3 class="panel-title">
          FIFO 拣货库位推荐
          <el-tag size="small" type="info" effect="plain">BR-003 · 按入库时间升序</el-tag>
        </h3>
        <el-table :data="fifo" border size="small">
          <el-table-column type="index" label="序" width="50" />
          <el-table-column prop="location_code" label="库位" width="140" class-name="mono" />
          <el-table-column prop="available" label="可用" width="90" align="right" />
          <el-table-column prop="first_in_at" label="最早入库时间" min-width="160" />
          <el-table-column label="建议取" width="90" align="right">
            <template #default="{ row }">{{ row.take_qty ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="useFifo(row)">用它</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-alert v-if="fifoShortage > 0" type="warning" :closable="false" class="mt8"
                  :title="`可用库存不足，缺口 ${fifoShortage} 件，可部分发料后拆单继续`" show-icon />
      </div>

      <div class="card mt16">
        <h3 class="panel-title">出库明细</h3>
        <el-table :data="order.items ?? []" border stripe>
          <el-table-column type="index" label="序号" width="60" />
          <el-table-column prop="sku_code" label="SKU 编码" width="180" class-name="mono" />
          <el-table-column prop="sn" label="SN 码" min-width="170" class-name="mono">
            <template #default="{ row }">{{ row.sn ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="库位" width="140">
            <template #default="{ row }">
              <span v-if="row.location_code" class="mono">{{ row.location_code }}</span>
              <el-tag v-else type="warning" size="small">未分配</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="出库状态" width="100">
            <template #default="{ row }">
              <el-tag :type="itemTag(row.status)" size="small">
                {{ ITEM_STATUS.find((s) => s.value === row.status)?.label ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="出库人" width="90">
            <template #default="{ row }">{{ row.operator_id ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="出库时间" width="165">
            <template #default="{ row }">{{ row.operated_at || '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <!-- 扫码拣货 -->
    <el-dialog v-model="pickDlg.visible" title="扫码拣货" width="470px">
      <el-form ref="pickRef" :model="pickForm" :rules="pickRules" label-width="90px">
        <el-form-item label="SN 码">
          <el-input v-model="pickForm.sn" placeholder="逐件出库时扫 SN（此时数量只能为 1）" maxlength="64" />
        </el-form-item>
        <el-form-item label="发货库位" prop="location_id">
          <el-select v-model="pickForm.location_id" filterable style="width: 100%">
            <el-option v-for="l in locations" :key="l.id" :value="l.id"
                       :disabled="l.status === 'LOCKED' || l.status === 'MAINTAIN'">
              <span class="mono">{{ l.code }}</span>
              <span class="muted"> · {{ l.warehouse_name }} ·
                {{ LOCATION_STATUS.find((s) => s.value === l.status)?.label }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="数量" prop="qty">
          <el-input-number v-model="pickForm.qty" :min="1" controls-position="right" />
          <span class="muted" style="margin-left: 8px">不带 SN 时可批量</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pickDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="pickDlg.saving" @click="doPick">确认拣货</el-button>
      </template>
    </el-dialog>

    <CheckDialog ref="checkRef" />
  </div>
</template>

<style scoped>
.crumb-bar { margin-bottom: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.acts { display: flex; gap: 8px; }
.warn { color: #e65c2e; font-weight: 600; }
</style>
