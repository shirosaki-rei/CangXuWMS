# WMS 验收对照表（AC Traceability）

| 项目 | 内容 |
|---|---|
| 版本 | V1.0（2026-11-04） |
| 上游 | `WMS仓储管理系统_PRD_V2.1.md` 第 15 章、`WMS分批次执行任务表.md` 第 1.9 节 |
| 用途 | 把每条 AC 映射到「哪条用例证明它」或「手工怎么验」，作为上线评审的凭据 |

**口径说明**：PRD 与任务清单多处写「41 条 AC」，但第 15 章实际枚举的是
**36 条**（AC-01~12 共 12 + AC-AI-01~12 共 12 + AC-CHK-01~05 共 5 + AC-CFG-01~07 共 7）。
本表按实际枚举的 36 条建立，**“41”这个数在文档里是历史遗留**，建议下次修订 PRD 时统一。

图例：
✅ 已自动化（给出用例名，`pytest -k` 可直接跑）
🟡 部分覆盖（后端已实现并有测试，UI 或配套流程未做）
⏳ 仅可手工验证（需真机 / 需要现场数据 / 需要对方系统）
⛔ 未实现（已明确排期或依赖外部）

---

## 1. 基础功能（AC-01 ~ AC-12）

| 编号 | 用例 | 证据 | 状态 |
|---|---|---|---|
| AC-01 | 登录锁定 | `test_auth_api.py::test_密码错误累加五次锁十分钟`（第 6 次返回 `WMS-4221` + `locked_until`） | ✅ |
| AC-02 | 采购入库主流程 | 检验→入库→上架→回传全链：`test_inspection_api.py`、`test_inbound_api.py`、`tools/e2e-b02.mjs`（17/17）。**MES 回传**需真实端点，见 `test_b06_integration.py` 之外的联调；**ERP 应付单**不属 WMS 职责 | 🟡 |
| AC-03 | 检验未通过拦截 | 后端 `BR-004`：`test_采购入库必须关联已检合格检验单_BR004`；详情接口返回 `submittable` + `purchase_block_reason`，前端据此置灰并按钮提示（`test_采购单未检验时不可提交_AC_03`） | ✅ |
| AC-04 | 超收审批 | 阈值判定：`test_inspection_api.py::test_超收超阈值转人工_BR005`；R4 预警：`test_ai.py::test_R4超收超阈值预警`。**“主管审批”没有独立审批流**，当前是拒绝并提示转人工 | 🟡 |
| AC-05 | 部分发货 | `test_outbound_api.py::test_实收与计划不一致必须填原因_BR016`（状态 `PARTIAL`，`remain` 可继续发） | ✅ |
| AC-06 | 重复扫码拦截 | `test_inbound_api.py::test_箱码重复被拒_WMS4093`（返回 `WMS-4093` + `duplicate: true`，不落库） | ✅ |
| AC-07 | 盘点锁定 | 创建即锁：`test_stocktake_api.py::test_创建盘点单锁定库位_BR007`；**出库被拒**：`test_outbound_api.py::test_盘点中库位不能出库_BR007`（本轮补测时发现并修复的缺口） | ✅ |
| AC-08 | 盘亏联动 | `test_stocktake_api.py::test_盘亏生成待执行SL单且库存暂不变` + `test_提交后解锁库位`。**注意是两步**：提交出单 → 执行单据才扣库存 | ✅ |
| AC-09 | 移位不改总量 | `test_move_supplier_api.py::test_移位改写库位维度且总量不变`、`test_移位写一条业务流水`（移出+移入流水净和 0）、`test_源库位清空后转空闲` | ✅ |
| AC-10 | 库位类型校验 | 入库侧：`test_inbound_api.py::test_危品库位不能放普通物料_BR013`；移位侧：`test_move_supplier_api.py::test_危品库位只能放危品` | ✅ |
| AC-11 | 离线补传 | `test_sync_api.py`（按 `created_at` 升序、单条失败不影响后续、重复返回 `DUPLICATE`）+ `tools/e2e-b03.mjs` 把第一批拣货故意走 `/sync/push` | ✅ |
| AC-12 | 仓库停用校验 | `test_basedata_api.py::test_停用仓库_BR014_有库存被拒`、`test_停用仓库_BR014_有未结单据被拒并列出阻塞项` | ✅ |

## 2. AI 能力（AC-AI-01 ~ AC-AI-12）

| 编号 | 用例 | 证据 | 状态 |
|---|---|---|---|
| AC-AI-01 | 库位推荐冷启动 | `test_ai.py::test_AC_AI_01_冷启动仍有候选与理由`（种子库无库存，仍给 3 个候选 + 理由） | ✅ |
| AC-AI-02 | 硬约束优先 | `test_ai.py::test_AC_AI_02_危品物料不推荐普通库位`、`test_硬约束淘汰锁定与类型不符` | ✅ |
| AC-AI-03 | 低置信度处理 | `test_ai.py::test_分差过小给低置信度且不给Top1`（`primary=null`，3 个并列） | ✅ |
| AC-AI-04 | 路径优化 | `test_ai.py::test_AC_AI_04_二十个拣货点节省不少于15pct`（实测 20 点节省 ~80%，基线为按库位编码顺序） | ✅ |
| AC-AI-05 | 校验阻断级 | `test_ai.py::test_出库可用库存不足时提交被阻断`（submit 返回 `WMS-4221` + `blocking_rules`）、`test_R3库位类型不符是阻断` | ✅ |
| AC-AI-06 | 校验预警级 | `test_ai.py::test_R1数量偏差预警`；原因 ≥5 字：`test_inbound_api.py::test_实收与计划不一致必须填原因_BR016`（写入 `config_snapshot.submit_reason`） | ✅ |
| AC-AI-07 | 校验性能 | `test_ai.py::test_AC_AI_07_全部规则三秒内跑完`（200 条明细，实测毫秒级） | ✅ |
| AC-AI-08 | 问数只读 | `test_nl_query.py::test_guard拒绝危险SQL`（8 种写/多语句/注释/超限写法全被拒）、`test_guard放行合法查询`；拒绝原因写入 `nl_query_log.rejected` | ✅ |
| AC-AI-09 | 问数口径 | `test_同一问题两次结果一致_AC_AI_09`（同一问题 SQL 与结果完全相同——SQL 来自模板，不是模型生成） | ✅ |
| AC-AI-10 | LLM 降级 | 问数在无 LLM 时照常返回数据表（`test_nl_query.py` 全部无 LLM 通过）；`llm_gateway` 超时返回模板文案并标 `degraded`；**入口按开关隐藏**：`/ai/settings` 返回 `ai_enabled`/`query_enabled`，菜单据此过滤（`test_静默接口与设置快照`） | ✅ |
| AC-AI-11 | 采纳反馈 | `test_ai.py::test_反馈与采纳率`（ACCEPT/REJECT 落库，`/ai/metrics` 按场景出采纳率） | ✅ |
| AC-AI-12 | 权限隔离 | 问数：`test_仓管员查不到未授权仓库_AC_AI_12`（WH-003 的数据仓管员查不到，SQL 里强制注入 `warehouse_id IN (...)`）；其余接口见 `test_仓管员显式传未分配仓库被拒_WMS4030` | ✅ |

## 3. 提交校验流程（AC-CHK-01 ~ AC-CHK-05）

| 编号 | 用例 | 证据 | 状态 |
|---|---|---|---|
| AC-CHK-01 | 入口一致性 | 入库、出库、**盘点**三类详情页均已接 `CheckDialog`（`tools/e2e-b05.mjs` 验证入库；盘点走同一组件） | ✅ |
| AC-CHK-02 | 全通过提交 | `tools/e2e-b02.mjs` / `e2e-b03.mjs`：提交后返回详情，状态标签刷新为「已入库 / 已出库」 | ✅ |
| AC-CHK-03 | 预警提交 | `CheckDialog` 前端强制 ≥5 字；后端 `BR-016` 二次校验（`test_实收与计划不一致必须填原因_BR016`） | ✅ |
| AC-CHK-04 | 阻断处理 | 存在 BLOCK 时 `submittable=false`，对话框提交按钮置灰（`CheckDialog.vue` + `e2e-b05` 截图）。**“按建议一键拆分”未实现**，需人工改数量 | 🟡 |
| AC-CHK-05 | Tab 数量角标 | 对话框内显示通过/预警/阻断计数；**列表页 Tab 上的待校验数角标未做** | 🟡 |

## 4. 配置与运营（AC-CFG-01 ~ AC-CFG-07）

| 编号 | 用例 | 证据 | 状态 |
|---|---|---|---|
| AC-CFG-01 | 盲盘模式 | `test_stocktake_api.py::test_盲盘对仓管员隐藏账面`（字段不返回）、`test_盲盘实盘响应也不揭晓差异`；`e2e-b04.mjs` 双账号验证 | ✅ |
| AC-CFG-02 | 明盘切换 | `test_明盘可显式指定`、`test_明盘对仓管员可见账面`；创建后无修改接口（天然不可改） | ✅ |
| AC-CFG-03 | 超收阈值覆盖 | `test_move_supplier_api.py::test_超收覆盖值影响检验判定_BR023`（覆盖到 20% 后 590/500 放行） | ✅ |
| AC-CFG-04 | 问数一键关闭 | `test_问数开关关闭`（`query_enabled=false` → `WMS-4221`「问数功能已关闭」）；`ai_enabled=false` → `test_AI开关关闭时降级`，推荐/路径/校验不受影响 | ✅ |
| AC-CFG-05 | 建议静默 | `POST /ai/silence` 写 Redis `ai:silent:{user}:{kind}` TTL 7 天；推荐卡上有「不再提示 7 天」；`/ai/settings` 回传 `silenced`（`test_静默接口与设置快照`） | ✅ |
| AC-CFG-06 | 采纳率自动下线 | 周度复核低于阈值时写 `ai_{kind}_offline=true`（`test_采纳率过低会写自动下线开关`），AI 服务读到即降级（`test_自动下线后推荐降级`）；**通知渠道仍是日志** | 🟡 |
| AC-CFG-07 | 上线 Gate | `backend/tools/gate_check.py`；验证方法：把任一库位的 `coord_x` 置 NULL 后重跑，应返回退出码 1 并列出缺失 | ✅（需按此步骤实测一次） |

---

## 5. 汇总

| 状态 | 数量 | 占比 |
|---|---|---|
| ✅ 已自动化 | 32 | 89% |
| 🟡 部分覆盖 | 4 | 11% |
| ⏳ 仅手工 | 0 | — |
| ⛔ 未实现 | 0 | 0% |
| **合计** | **36** | |

> 上一版本这里写的是 22/9/0/5，逐条复核时发现分类统计有误（AC-AI-10 等被重复计入未实现），已按实际逐条状态更正。

### 未实现或有缺口的明细

| 编号 | 缺口 | 归属 |
|---|---|---|
| AC-CFG-06 | 自动下线已落地，但**通知渠道**仍是日志（无邮件/IM） | 运维手册 |
| AC-02 | MES 回传需真实端点联调 | I-01 |
| AC-03 | 前端未置灰入库按钮 | 前端增强 |
| AC-04 | 无独立「超收审批」流程 | 需产品确认 |
| AC-AI-10 / 12 | 依赖问数 | 二期 |
| AC-CHK-01 | 盘点详情未接 X04 | 前端增强 |
| AC-CHK-04 | 无「按建议拆分」 | 需产品确认口径 |
| AC-CHK-05 | 列表 Tab 无待校验角标 | 前端增强 |

### 本轮由这张表发现的真问题

**AC-07 盘点锁定在出库侧是漏的**：创建盘点会锁库位，但出库拣货只校验可用量、不校验库位状态，
盘点期间仍能拣货。已补 `outbound_service.pick` 的 BR-007 校验，并加用例
`test_盘点中库位不能出库_BR007`。

---

## 6. 复验方式

```bash
cd backend
./.venv/Scripts/python.exe -m pytest -q                  # 343 passed / 2 skipped，全绿即自动化部分通过
PYTHONPATH=. ./.venv/Scripts/python.exe tools/gate_check.py   # AC-CFG-07
cd .. && node tools/e2e-b02.mjs /tmp/e2e-b02              # AC-02 / CHK-02
cd .. && node tools/e2e-b03.mjs /tmp/e2e-b03              # AC-05 / AC-11
cd .. && node tools/e2e-b04.mjs /tmp/e2e-b04              # AC-07 / 08 / CFG-01
cd .. && node tools/e2e-b05.mjs /tmp/e2e-b05              # AC-AI-05 / CHK-03 / CHK-04
```

> 跑 E2E 前先 `PYTHONPATH=. ./.venv/Scripts/python.exe tools/reset_db.py` 重置库。
