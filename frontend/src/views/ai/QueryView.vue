<script setup lang="ts">
/** X01 智能问数。只读：SQL 由服务端模板生成，前端只负责提问和展示。 */
import { onMounted, ref } from 'vue'
import { queryApi, type QueryResult } from '@/api/ai'
import { useUserStore } from '@/stores/user'

const user = useUserStore()
const question = ref('')
const loading = ref(false)
const result = ref<QueryResult | null>(null)
const history = ref<{ q: string; r: QueryResult }[]>([])

const SAMPLES = [
  '上周 A3288 出了多少台？',
  '近 7 天入库多少',
  '现在物料库存',
  '哪些物料低库存',
]

async function ask(q?: string) {
  const text = (q ?? question.value).trim()
  if (!text) return
  loading.value = true
  try {
    const r = await queryApi.ask(text)
    result.value = r
    history.value.unshift({ q: text, r })
    history.value = history.value.slice(0, 10)
    question.value = ''
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!user.me) await user.loadMe()
})
</script>

<template>
  <div>
    <h2 class="panel-title">智能问数（X01）</h2>
    <p class="muted" style="margin-bottom: 12px">
      答案是 SQL 算出来的，不是模型编的：问题只用来匹配预置指标模板。
      没有对应模板时会明确告诉你「暂无数据」，不会现编一条查询。
    </p>

    <div class="ask">
      <el-input v-model="question" size="large" placeholder="例如：上周 A3288 出了多少台？"
                @keyup.enter="ask()" clearable />
      <el-button type="primary" size="large" :loading="loading" @click="ask()">提问</el-button>
    </div>

    <div class="samples">
      <span class="muted">试试：</span>
      <el-tag v-for="s in SAMPLES" :key="s" class="chip" @click="ask(s)">{{ s }}</el-tag>
    </div>

    <template v-if="result">
      <div class="card mt16">
        <div class="head">
          <el-tag v-if="result.metric" size="small" effect="plain">{{ result.metric }}</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">未命中模板</el-tag>
          <el-tag v-if="result.degraded" size="small" type="warning">LLM 超时 · 已降级为模板文案</el-tag>
          <span class="muted">共 {{ result.row_count }} 行 · {{ result.trace_id }}</span>
        </div>
        <p class="conclusion">{{ result.conclusion }}</p>
        <p v-if="result.caliber" class="muted">口径：{{ result.caliber }}</p>

        <el-table v-if="result.table.columns.length" :data="result.table.rows.map((r) => Object.fromEntries(r.map((v, i) => [String(i), v])))"
                  border size="small" class="mt8">
          <el-table-column v-for="(c, i) in result.table.columns" :key="c" :label="c" :prop="String(i)" />
        </el-table>

        <el-collapse v-if="result.sql" class="mt8">
          <el-collapse-item title="查看生成的 SQL" name="sql">
            <pre class="sql">{{ result.sql }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </template>

    <template v-if="history.length > 1">
      <h3 class="panel-title mt16">最近提问</h3>
      <div v-for="(h, i) in history.slice(1)" :key="i" class="hist" @click="result = h.r">
        <span>{{ h.q }}</span>
        <span class="muted">{{ h.r.row_count }} 行</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ask { display: flex; gap: 10px; }
.samples { margin-top: 10px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.chip { cursor: pointer; }
.head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.conclusion { font-size: 16px; color: #12263a; margin: 10px 0 4px; }
.sql {
  background: #f6f8fa; padding: 10px; border-radius: 4px; font-size: 12px;
  white-space: pre-wrap; word-break: break-all; color: #334;
}
.hist {
  display: flex; justify-content: space-between; padding: 8px 10px; background: #fff;
  border: 1px solid #e9eef4; border-radius: 4px; margin-bottom: 6px; cursor: pointer;
  font-size: 13px;
}
.hist:hover { border-color: #1891ff; }
</style>
