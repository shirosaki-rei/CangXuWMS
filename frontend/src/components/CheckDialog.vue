<script setup lang="ts">
/** X04 提交前校验对话框。三 Tab（入库/出库/盘点）在调用方决定，这里只渲染结果。 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { aiApi, LEVEL_LABEL, LEVEL_TAG, type CheckResult } from '@/api/ai'

const visible = ref(false)
const loading = ref(false)
const result = ref<CheckResult | null>(null)
const reason = ref('')
const submitting = ref(false)
let target: { orderType: string; id: number; onPass: (reason?: string) => Promise<void> } | null = null

const needReason = computed(() => (result.value?.summary.warn ?? 0) > 0)
const blocked = computed(() => result.value?.submittable === false)

async function open(orderType: string, id: number, onPass: (reason?: string) => Promise<void>) {
  target = { orderType, id, onPass }
  visible.value = true
  reason.value = ''
  loading.value = true
  try {
    result.value = await aiApi.checks(orderType, id)
  } finally {
    loading.value = false
  }
}

async function confirm() {
  if (!target || !result.value) return
  if (blocked.value) return
  if (needReason.value && reason.value.trim().length < 5) {
    ElMessage.warning('存在预警项，请填写原因（至少 5 个字）')
    return
  }
  submitting.value = true
  try {
    await target.onPass(reason.value.trim() || undefined)
    // 采纳记录：本次提交是「人确认了 AI 的建议」
    if (result.value.suggestion_id) {
      void aiApi.feedback(result.value.suggestion_id, 'ACCEPT').catch(() => undefined)
    }
    visible.value = false
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog v-model="visible" title="提交前校验（X04）" width="640px">
    <div v-loading="loading">
      <template v-if="result">
        <div class="sum">
          <el-tag type="success">通过 {{ result.summary.pass }}</el-tag>
          <el-tag type="warning">预警 {{ result.summary.warn }}</el-tag>
          <el-tag type="danger">阻断 {{ result.summary.block }}</el-tag>
          <el-tag type="info">不适用 {{ result.summary.skipped }}</el-tag>
          <span class="muted">耗时 {{ result.elapsed_ms }}ms</span>
        </div>

        <el-alert
          v-if="blocked"
          type="error"
          :closable="false"
          show-icon
          class="mt8"
          title="存在阻断项，提交按钮不可用；请按处置建议修正后重新校验（BR-017）"
        />

        <div class="list">
          <div v-for="r in result.results" :key="r.rule" class="row">
            <el-tag :type="LEVEL_TAG[r.level]" size="small" effect="dark" class="rule">
              {{ r.rule }}
            </el-tag>
            <div class="body">
              <div class="title">
                {{ r.title }}
                <el-tag :type="LEVEL_TAG[r.level]" size="small" effect="plain">
                  {{ LEVEL_LABEL[r.level] }}
                </el-tag>
              </div>
              <div v-if="r.detail" class="detail">{{ r.detail }}</div>
              <div v-if="r.actions?.length" class="actions">
                <el-button v-for="a in r.actions" :key="a" link type="primary" size="small">
                  {{ a }}
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <el-form v-if="needReason && !blocked" label-width="80px" class="mt16">
          <el-form-item label="差异原因">
            <el-input v-model="reason" type="textarea" :rows="2" maxlength="255"
                      placeholder="存在预警项，必须填写原因（≥5 字），会写入审计日志" />
          </el-form-item>
        </el-form>
      </template>
    </div>

    <template #footer>
      <el-button @click="visible = false">返回修改</el-button>
      <el-button type="primary" :disabled="blocked" :loading="submitting" @click="confirm">
        {{ blocked ? '存在阻断项' : '确认提交' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.sum { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.list { margin-top: 14px; max-height: 320px; overflow: auto; }
.row {
  display: flex; gap: 10px; padding: 10px; border-bottom: 1px solid #eef2f6;
}
.rule { flex: 0 0 auto; height: 22px; }
.body { flex: 1; }
.title { font-size: 13px; color: #222; display: flex; gap: 6px; align-items: center; }
.detail { font-size: 12px; color: #7b8a99; margin-top: 3px; }
.actions { margin-top: 2px; }
.muted { color: #999; font-size: 12px; margin-left: 6px; }
</style>
