<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance } from 'element-plus'
import { systemApi, type SysConfig } from '@/api/system'

const loading = ref(false)
const rows = ref<SysConfig[]>([])
const editing = ref<SysConfig | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ cfg_value: '', remark: '' })

/** 配置项中文名（PRD 6.9 的 10 项） */
const LABELS: Record<string, string> = {
  over_receive_ratio: '超收阈值',
  qty_deviation_ratio: '数量偏差阈值',
  stocktake_mode: '盘点方式',
  diff_rate_ratio: '盘点差异率阈值',
  coord_required: '库位坐标必填',
  attr_complete_ratio: '属性完整率下限',
  ai_enabled: '建议展示总开关',
  silent_days: '单类建议静默期',
  query_enabled: '问数功能开关',
  adoption_offline_ratio: '采纳率下线阈值',
}

const TYPE_HINT: Record<string, string> = {
  INT: '整数',
  DECIMAL: '小数，如 0.05 表示 5%',
  BOOL: 'true / false',
  ENUM: '枚举值',
  STRING: '文本',
}

async function load() {
  loading.value = true
  try {
    rows.value = await systemApi.configs()
  } finally {
    loading.value = false
  }
}

function openEdit(row: SysConfig) {
  editing.value = row
  form.cfg_value = row.cfg_value
  form.remark = row.remark ?? ''
}

async function save() {
  if (!editing.value) return
  saving.value = true
  try {
    await systemApi.upsertConfig({
      cfg_key: editing.value.cfg_key,
      cfg_value: form.cfg_value,
      value_type: editing.value.value_type,
      scope: 'GLOBAL',
      remark: form.remark || undefined,
    })
    ElMessage.success('已保存（仅对新建单据生效，BR-026）')
    editing.value = null
    load()
  } finally {
    saving.value = false
  }
}

function label(key: string) {
  return LABELS[key] ?? key
}

onMounted(load)
</script>

<template>
  <div>
    <h2 class="panel-title">规则配置（PRD 6.9）</h2>
    <p class="muted" style="margin-bottom: 12px">
      修改后<strong>仅对新建单据生效</strong>，在途单据沿用创建时的快照值（BR-026）。
    </p>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column label="配置项" min-width="180">
        <template #default="{ row }">
          <div>{{ label(row.cfg_key) }}</div>
          <div class="muted mono">{{ row.cfg_key }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="cfg_value" label="当前值" width="130">
        <template #default="{ row }">
          <el-tag size="small" effect="dark">{{ row.cfg_value }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="150">
        <template #default="{ row }">
          <span>{{ row.value_type }}</span>
          <span class="muted"> · {{ TYPE_HINT[row.value_type] ?? '' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="说明" min-width="220" show-overflow-tooltip />
      <el-table-column prop="updated_at" label="更新时间" width="170" />
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">修改</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="editing" :title="editing ? `修改「${label(editing.cfg_key)}」` : ''" width="440px">
      <el-form v-if="editing" ref="formRef" :model="form" label-width="72px">
        <el-form-item label="配置键">
          <el-input :model-value="editing.cfg_key" disabled />
        </el-form-item>
        <el-form-item label="新值">
          <el-input v-model="form.cfg_value" maxlength="255" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editing = null">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
