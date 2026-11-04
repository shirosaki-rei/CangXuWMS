<script setup lang="ts">
/** X05 AI 效果看板。只读展示，数据来自 /ai/metrics + metric_event 埋点。 */
import { onMounted, ref } from 'vue'
import { aiApi, type Metrics } from '@/api/ai'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const loading = ref(false)
const m = ref<Metrics | null>(null)
const days = ref(30)

const TYPE_LABEL: Record<string, string> = {
  LOCATION: '库位推荐', PATH: '拣货路径', CHECK: '提交校验',
}
const SCENE_LABEL: Record<string, string> = {
  LOCATE: '找位', PICK: '拣货', CHECK: '校验', QUERY: '问数',
}

async function load() {
  loading.value = true
  try {
    m.value = await aiApi.metrics(days.value)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
  load()
})
</script>

<template>
  <div v-loading="loading">
    <h2 class="panel-title">AI 效果看板（X05）</h2>

    <div class="toolbar">
      <el-radio-group v-model="days" @change="load">
        <el-radio-button :value="7">近 7 天</el-radio-button>
        <el-radio-button :value="30">近 30 天</el-radio-button>
        <el-radio-button :value="90">近 90 天</el-radio-button>
      </el-radio-group>
    </div>

    <template v-if="m">
      <div class="stats">
        <div class="stat">
          <div class="v">{{ m.suggestion_total }}</div>
          <div class="l">建议总数</div>
        </div>
        <div class="stat">
          <div class="v">{{ (m.offline_threshold * 100).toFixed(0) }}%</div>
          <div class="l">采纳率下线阈值（BR-022）</div>
        </div>
        <div class="stat">
          <div class="v">{{ m.adoption.length }}</div>
          <div class="l">有反馈的建议类型</div>
        </div>
      </div>

      <div class="card mt16">
        <h3 class="panel-title">采纳率</h3>
        <el-table :data="m.adoption" border>
          <el-table-column label="建议类型" width="140">
            <template #default="{ row }">{{ TYPE_LABEL[row.type] ?? row.type }}</template>
          </el-table-column>
          <el-table-column prop="accept" label="采纳" width="80" align="right" />
          <el-table-column prop="reject" label="拒绝" width="80" align="right" />
          <el-table-column prop="revoke" label="撤销" width="80" align="right" />
          <el-table-column label="采纳率" width="200">
            <template #default="{ row }">
              <template v-if="row.rate !== null">
                <el-progress :percentage="row.rate" :stroke-width="10"
                             :status="row.rate / 100 < m.offline_threshold ? 'warning' : 'success'" />
              </template>
              <span v-else class="muted">暂无反馈</span>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="!m.adoption.length" class="muted mt8">
          还没有反馈数据。用户对建议点「采纳 / 不合适」后这里才有数。
        </p>
      </div>

      <div class="card mt16">
        <h3 class="panel-title">结果指标（来自 metric_event 埋点）</h3>
        <el-table :data="m.scenes" border>
          <el-table-column label="场景" width="110">
            <template #default="{ row }">{{ SCENE_LABEL[row.scene] ?? row.scene }}</template>
          </el-table-column>
          <el-table-column prop="count" label="样本" width="90" align="right" />
          <el-table-column label="平均耗时" width="120" align="right">
            <template #default="{ row }">{{ row.avg_duration_ms }} ms</template>
          </el-table-column>
          <el-table-column label="AI 距离" width="110" align="right">
            <template #default="{ row }">{{ row.avg_distance_m }} m</template>
          </el-table-column>
          <el-table-column label="基线距离" width="110" align="right">
            <template #default="{ row }">{{ row.avg_baseline_m }} m</template>
          </el-table-column>
          <el-table-column label="节省" width="100" align="right">
            <template #default="{ row }">
              <span v-if="row.saved_pct !== null" class="gain">{{ row.saved_pct }}%</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="!m.scenes.length" class="muted mt8">
          还没有埋点数据。埋点写入时机：APP 扫码定位 / 拣货完成时上报 metric_event。
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.stats { display: flex; gap: 14px; }
.stat {
  flex: 1; background: #fff; border: 1px solid #e5e5e5; border-radius: 3px;
  padding: 16px 18px;
}
.stat .v { font-size: 22px; font-weight: 600; color: #1891ff; }
.stat .l { font-size: 12px; color: #999; margin-top: 4px; }
.gain { color: #18a058; font-weight: 600; }
</style>
