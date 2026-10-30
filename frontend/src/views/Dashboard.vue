<script setup lang="ts">
import { computed } from 'vue'
import { useUserStore } from '@/stores/user'

const user = useUserStore()

/** B01 只交付基建 + 基础资料 + 账号权限；后续批次的功能入口在此登记 */
const roadmap = [
  { phase: 'B01 · 已完成', items: ['工程骨架与统一错误码', '认证 / 权限 / 数据权限', '仓库 / 库位 / 条码', '账号 / 角色 / 规则配置'] },
  { phase: 'B02 · 计划中', items: ['实时库存查询 P01–P02', '出入库流水 P03–P04', '采购入库闭环', '来料检验 P14'] },
  { phase: 'B03 · 计划中', items: ['出库三类单据 P10–P13', '扫码拣货与 FIFO', '离线补传 /sync/push'] },
  { phase: 'B04 · 计划中', items: ['盘点 P15–P16', '移位 P17', '供应商档案'] },
  { phase: 'B05 · 计划中', items: ['库位推荐 X02', '拣货路径 X03', '提交前校验 X04', 'AI 效果看板 X05'] },
  { phase: 'B06 · 计划中', items: ['MES / ERP 集成', '每日对账', '压测与 41 条 AC 验收'] },
]

const stats = computed(() => [
  { label: '当前角色', value: user.me?.role_label ?? '-' },
  { label: '可见仓库', value: `${user.me?.warehouses.length ?? 0} 个` },
  { label: '已授权功能', value: `${user.me?.permissions.length ?? 0} 项` },
])
</script>

<template>
  <div>
    <h2 class="panel-title">工作台</h2>

    <div class="stat-row">
      <div v-for="s in stats" :key="s.label" class="stat">
        <div class="stat-v">{{ s.value }}</div>
        <div class="stat-l">{{ s.label }}</div>
      </div>
    </div>

    <h2 class="panel-title mt16">分批交付进度</h2>
    <div class="card">
      <el-timeline>
        <el-timeline-item
          v-for="r in roadmap"
          :key="r.phase"
          :type="r.phase.includes('已完成') ? 'success' : 'info'"
          :timestamp="r.phase"
          placement="top"
        >
          <div class="chips">
            <el-tag v-for="i in r.items" :key="i" size="small" effect="plain" class="chip">{{ i }}</el-tag>
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>
  </div>
</template>

<style scoped>
.stat-row { display: flex; gap: 14px; }
.stat {
  flex: 1;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 18px 20px;
}
.stat-v { font-size: 24px; font-weight: 600; color: var(--blue); }
.stat-l { font-size: 12px; color: var(--muted); margin-top: 4px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { margin: 0; }
</style>
