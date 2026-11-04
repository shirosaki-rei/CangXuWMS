<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { stocktakeApi, type Stocktake, type StocktakeItem } from '@/api/stocktake'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const id = Number(route.params.id)
const loading = ref(false)
const order = ref<Stocktake | null>(null)
const items = ref<StocktakeItem[]>([])
const canSubmit = ref(false)

/** 盲盘时后端根本不返回 book_qty，前端不用再判断，直接按字段有没有渲染 */
const isBlind = computed(() => order.value?.mode === 'BLIND')
const hideBook = computed(() => isBlind.value && items.value.every((i) => i.book_qty === undefined))

async function load() {
  loading.value = true
  try {
    order.value = await stocktakeApi.detail(id)
    items.value = await stocktakeApi.items(id)
  } finally {
    loading.value = false
  }
}

function statusTag(s?: string) {
  return s === 'DONE' ? 'success' : s === 'CANCELED' ? 'danger'
    : s === 'CONFIRMING' ? 'primary' : s === 'COUNTING' ? 'warning' : 'info'
}

// ---------------------------------------------------------------- 录入实盘
const countDlg = reactive({ visible: false, saving: false, row: null as StocktakeItem | null, real_qty: 0 })

function openCount(row: StocktakeItem) {
  countDlg.row = row
  countDlg.real_qty = row.real_qty ?? 0
  countDlg.visible = true
}

async function doCount() {
  const r = countDlg.row
  if (!r) return
  countDlg.saving = true
  try {
    await stocktakeApi.count(id, {
      location_id: r.location_id,
      material_id: r.material_id,
      real_qty: countDlg.real_qty,
    })
    ElMessage.success('已记录实盘数')
    countDlg.visible = false
    await load()
  } finally {
    countDlg.saving = false
  }
}

// ---------------------------------------------------------------- 提交
async function doSubmit() {
  await ElMessageBox.confirm(
    '提交后按差异生成「待执行」的盘亏出库单 / 盘盈入库单并解锁库位；' +
    '库存要等仓管员执行对应单据后才变动。确认提交？',
    '提交盘点',
    { type: 'warning' },
  )
  const r = await stocktakeApi.submit(id)
  const parts = [`盘亏 ${r.diff_loss} 条`, `盘盈 ${r.diff_gain} 条`]
  if (r.loss_no) parts.push(`盘亏单 ${r.loss_no}（待执行）`)
  if (r.gain_no) parts.push(`盘盈单 ${r.gain_no}（待执行）`)
  ElMessage.success(parts.join('，'))
  await load()
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  canSubmit.value = !!user.me?.permissions.includes('stocktake:manage')
  await load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="crumb-bar">
      <el-button link type="primary" @click="router.push('/stocktake')">← 返回盘点列表</el-button>
    </div>

    <template v-if="order">
      <div class="head">
        <h2 class="panel-title" style="margin: 0">
          盘点详情（P16） · <span class="mono">{{ order.no }}</span>
        </h2>
        <div class="acts">
          <el-button
            v-if="canSubmit && !order.terminal && order.undone === 0"
            type="primary"
            @click="doSubmit"
          >
            提交盘点
          </el-button>
        </div>
      </div>

      <div class="card">
        <h3 class="panel-title">盘点信息</h3>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="盘点单号">{{ order.no }}</el-descriptions-item>
          <el-descriptions-item label="盘点类型">{{ order.type_label }}</el-descriptions-item>
          <el-descriptions-item label="盘点方式">
            <el-tag size="small" :type="isBlind ? 'warning' : 'info'" effect="plain">
              {{ order.mode_label }}{{ isBlind ? ' · 生产默认盲盘' : '' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="盘点仓库">{{ order.warehouse_name ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="全部 / 已盘 / 未盘">
            {{ order.total }} / {{ order.done }} / {{ order.undone }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTag(order.status)" size="small">{{ order.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="盘亏 / 盘盈">
            <span class="loss">{{ order.diff_loss }}</span> /
            <span class="gain">{{ order.diff_gain }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ order.created_at }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ order.finished_at ?? '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="order.status === 'DONE' && (order.diff_loss || order.diff_gain)"
          class="mt8"
          type="info"
          :closable="false"
          show-icon
          title="盈亏单据已生成但尚未执行，库存未变动；请到「出库单 / 入库单」里执行对应单据"
        />
        <el-alert
          v-if="hideBook"
          class="mt8"
          type="warning"
          :closable="false"
          show-icon
          title="盲盘模式：账面与差异在提交后才揭晓"
        />
      </div>

      <div class="card mt16">
        <h3 class="panel-title">盘点明细</h3>
        <el-table :data="items" border stripe>
          <el-table-column type="index" label="序号" width="60" />
          <el-table-column prop="material_name" label="物料名称" min-width="170" />
          <el-table-column prop="location_code" label="库位" width="130" class-name="mono" />
          <el-table-column label="账面" width="90" align="right">
            <template #default="{ row }">
              <span v-if="row.book_qty !== undefined">{{ row.book_qty }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="实盘" width="90" align="right">
            <template #default="{ row }">
              <span v-if="row.counted">{{ row.real_qty }}</span>
              <span v-else class="muted">未盘</span>
            </template>
          </el-table-column>
          <el-table-column label="盘亏 / 盘盈" width="120" align="right">
            <template #default="{ row }">
              <template v-if="row.diff !== undefined">
                <span v-if="row.diff < 0" class="loss">{{ row.diff }}</span>
                <span v-else-if="row.diff > 0" class="gain">+{{ row.diff }}</span>
                <span v-else class="muted">0</span>
              </template>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="单位" width="70">
            <template #default="{ row }">{{ row.unit }}</template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button v-if="!order?.terminal" link type="primary" @click="openCount(row)">
                录实盘
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="muted mt8">
          未盘条目的「实盘」为空而非 0；提交前必须全部盘完，不允许部分提交。
        </p>
      </div>
    </template>

    <el-dialog v-model="countDlg.visible" title="录入实盘数" width="400px">
      <p class="muted">
        {{ countDlg.row?.material_name }} · {{ countDlg.row?.location_code }}
      </p>
      <el-form label-width="70px" class="mt8">
        <el-form-item label="实盘数">
          <el-input-number v-model="countDlg.real_qty" :min="0" controls-position="right" />
          <span class="muted" style="margin-left: 8px">{{ countDlg.row?.unit }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="countDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="countDlg.saving" @click="doCount">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.crumb-bar { margin-bottom: 10px; }
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.acts { display: flex; gap: 8px; }
.loss { color: #d03050; font-weight: 600; }
.gain { color: #18a058; font-weight: 600; }
</style>
