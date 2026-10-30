# WMS 仓储管理系统 · 接口文档（API Contract）

| 项目 | 内容 |
|---|---|
| 文档版本 | V1.0 |
| 编写日期 | 2026-10-29 |
| 上游文档 | `WMS仓储管理系统_PRD_V2.1.md`（需求）、`WMS架构设计文档.md`（架构与 DDL） |
| 适用范围 | 全部对外接口：PC 后台、仓储 APP、MES / ERP 集成 |
| 接口总数 | 业务接口 58 个 + 集成接口 6 个 = 64 |

> **单一数据源**：接口路径、参数、错误码以本文档为准；架构文档 7.3 只保留清单索引，若与本文档冲突，改本文档并同步架构 7.3。

---

## 1. 通用约定

### 1.1 基础

| 项 | 约定 |
|---|---|
| 前缀 | `/api/v1` |
| 协议 | HTTPS；JSON over HTTP；`Content-Type: application/json; charset=utf-8` |
| 认证 | 用户端 `Authorization: Bearer <JWT>`（access 2h 滑动 / 8h 无操作作废 / refresh 7d）；集成端用 `X-App-Key` + `X-Timestamp` + `X-Sign`（HMAC-SHA256，见 6.2） |
| 响应体 | `{ "code": 0, "message": "ok", "data": {}, "trace_id": "..." }`；`code != 0` 时 `data` 为 `null` |
| 分页 | `?page=1&page_size=20`（`page_size` ≤ 100）；响应含 `total` |
| 时间 | 请求/响应均为 ISO 8601 UTC（`2026-01-27T10:20:00Z`），展示层转本地时区 |
| 幂等 | 所有写操作必须带 `client_op_id`（Header `X-Client-Op-Id` 优先，其次 body 字段） |
| 排序 | 列表默认按业务时间倒序；稳定排序必须带 `id` 作为次级键 |

### 1.2 错误码

`code` 与 HTTP 状态码分离：HTTP 表示传输层结果，`code` 表示业务结果。`code != 0` 时 HTTP 仍为 200，除非是传输/认证层错误。

| code | HTTP | 含义 | 前端 / 调用方处理 |
|---|---|---|---|
| 0 | 200 | 成功 | — |
| `WMS-4001` | 400 | 参数校验失败 | 高亮字段，`data.fields` 给出字段级错误 |
| `WMS-4010` | 401 | 未登录 / token 过期 | 跳登录；已过期 refresh 一次再重试 |
| `WMS-4011` | 401 | 签名错误 / 时间戳超时（集成端） | 告警，不重试（重试同样失败） |
| `WMS-4030` | 403 | 无权限（含跨仓越权） | 提示无权限，不暴露资源是否存在 |
| `WMS-4091` | 200 | 幂等重放 | **视为成功**，直接采用返回的原结果 |
| `WMS-4092` | 200 | 单据已关闭 / 已作废 | 提示并刷新列表 |
| `WMS-4093` | 200 | 箱码 / SN 重复 | 标红该行，允许跳过不阻断 |
| `WMS-4094` | 200 | 版本冲突（乐观锁） | 拉取最新单据后重试一次 |
| `WMS-4221` | 200 | 业务规则不满足 | 展示 `message`，按规则编号给处置建议 |
| `WMS-4222` | 200 | 可用库存不足 | 提示缺口数量，建议拆单 |
| `WMS-4290` | 429 | 触发限流 | 指数退避重试；LLM 限流见 5.5 |
| `WMS-5000` | 500 | 服务端异常 | 提示稍后重试 + 报上 `trace_id` |

### 1.3 幂等协议

```
1. 客户端每次"用户意图"生成一个 UUID v4 作为 client_op_id，落本地库（不可每次启动重新生成）
2. 写请求带上它 → 服务端 Redis SETNX idem:{client_op_id}（TTL 24h）
3. 首次：执行业务，把完整响应写入 op_log.result，返回
4. 重放：SETNX 失败 → 查 op_log → 原样返回首次结果，code=WMS-4091
5. Redis 键过期后的重放：DB 唯一索引 uk_client_op 兜底，行为同 4
```

APP 卸载重装会丢本地队列与 UUID（ADR-004 已知后果）：首次启动时校验队列完整性，提示用户「有 N 条未同步记录可能丢失」。

### 1.4 数据权限

所有查询接口在依赖注入层强制注入当前用户的可见仓库范围（`user_warehouse`），**不接受前端传 `warehouse_id` 绕过**。仓管员仅见被分配仓库；主管/管理员见全部；集成账号不受此限但只能看自己业务域的接口。

---

## 2. 接口清单索引

图例：**权限** K=仓管员 I=检验员 S=主管 A=管理员 M=集成账号（可多选）；**幂等** ✓=必须带 `client_op_id`。

### 2.1 认证（3）

| # | 方法 | 路径 | 权限 | 幂等 | 对应页面 |
|---|---|---|---|---|---|
| 1 | POST | `/auth/login` | 匿名 | — | L01 |
| 2 | POST | `/auth/refresh` | 匿名 | — | — |
| 3 | POST | `/auth/logout` | 全部 | — | — |

### 2.2 库存与单据查询（22）

| # | 方法 | 路径 | 权限 | 对应页面 |
|---|---|---|---|---|
| 4 | GET | `/inventory/products` | K/I/S/A | P01 |
| 5 | GET | `/inventory/materials` | K/I/S/A | P02 |
| 6 | GET | `/txn` | K/I/S/A | P03 / P04 |
| 7 | GET | `/inbound-orders` | K/S | P05–P08 |
| 8 | GET | `/inbound-orders/{id}` | K/S | P09 |
| 9 | GET | `/outbound-orders` | K/S | P10–P12 |
| 10 | GET | `/outbound-orders/{id}` | K/S | P13 |
| 11 | GET | `/inspections` | I/S | P14 |
| 12 | GET | `/inspections/{id}` | I/S | P14 详情 |
| 13 | GET | `/stocktakes` | S | P15 |
| 14 | GET | `/stocktakes/{id}` | S | P16 |
| 15 | GET | `/stocktakes/{id}/items` | S/K(盲盘不见账面) | P16 明细 |
| 16 | GET | `/move-orders` | K/S | P17 |
| 17 | GET | `/move-orders/{id}` | K/S | P17 详情 |
| 18 | GET | `/warehouses` | 全部 | P18 |
| 19 | GET | `/locations` | 全部 | P19 |
| 20 | GET | `/barcodes` | 全部 | P20 |
| 21 | GET | `/suppliers` | S/A | — |
| 22 | GET | `/users` | A | — |
| 23 | GET | `/roles` | A | — |
| 24 | GET | `/sys-configs` | A | 基础设置→规则配置 |
| 25 | GET | `/export/{biz}` | 按 biz 继承 | P01–P04 导出 |

### 2.3 写操作（13，均需 `client_op_id`）

| # | 方法 | 路径 | 权限 | 幂等 | 对应页面 |
|---|---|---|---|---|---|
| 26 | POST | `/inbound-orders/{id}/scan` | K | ✓ | A02 / A03 / A04 |
| 27 | POST | `/inbound-orders/{id}/submit` | K/S | ✓ | P09 → X04 |
| 28 | POST | `/outbound-orders/{id}/pick` | K | ✓ | A07 / A08 |
| 29 | POST | `/outbound-orders/{id}/submit` | K/S | ✓ | P13 → X04 |
| 30 | POST | `/stocktakes/{id}/count` | K/S | ✓ | A09 |
| 31 | POST | `/stocktakes/{id}/submit` | S | ✓ | P16 → X04 |
| 32 | POST | `/stocktakes` | S | ✓ | P15 |
| 33 | POST | `/move-orders` | K | ✓ | A09 / P17 |
| 34 | POST | `/inspections/{id}/scan` | I | ✓ | A05 |
| 35 | POST | `/inspections/{id}/judge` | I | ✓ | A05 / P14 |
| 36 | POST | `/inspections/{id}/gen-inbound` | I/S | ✓ | P14 |
| 37 | POST | `/inbound-orders/{id}/void` | S | ✓ | P09 |
| 38 | POST | `/outbound-orders/{id}/void` | S | ✓ | P13 |

### 2.4 基础资料维护（9，仅管理员，均需 `client_op_id`）

| # | 方法 | 路径 | 对应页面 |
|---|---|---|---|
| 39 | POST | `/warehouses` | P18 |
| 40 | PUT | `/warehouses/{id}` | P18 |
| 41 | POST | `/warehouses/{id}/toggle` | P18 |
| 42 | POST | `/locations` | P19 |
| 43 | PUT | `/locations/{id}` | P19 |
| 44 | POST | `/locations/{id}/status` | P19 |
| 45 | POST | `/barcodes` | P20 |
| 46 | POST | `/barcodes/print` | P20 |
| 47 | PUT | `/suppliers/{id}` | 供应商档案 |

### 2.5 账号与权限（4，仅管理员）

| # | 方法 | 路径 |
|---|---|---|
| 48 | POST | `/users` |
| 49 | PUT | `/users/{id}` |
| 50 | POST | `/users/{id}/roles` |
| 51 | PUT | `/sys-configs` |

### 2.6 AI 能力（6，除反馈外全部只读）

| # | 方法 | 路径 | 权限 | 对应页面 |
|---|---|---|---|---|
| 52 | POST | `/ai/locations/recommend` | K/S | X02 |
| 53 | POST | `/ai/picking/optimize` | K | X03 / A08 |
| 54 | POST | `/ai/checks/{order_type}/{id}` | K/S | X04 |
| 55 | POST | `/ai/query` | K(本仓)/S/A | X01 |
| 56 | GET | `/ai/metrics` | S/A | X05 |
| 57 | POST | `/ai/feedback` | K/S/A | X02–X04 |

### 2.7 离线同步（1）

| # | 方法 | 路径 | 权限 |
|---|---|---|---|
| 58 | POST | `/sync/push` | K |

### 2.8 集成接口（6，仅 MES / ERP）

| # | 方向 | 路径 | 幂等键 |
|---|---|---|---|
| 59 | MES → WMS | `POST /integration/outbound-orders` | `no + version` |
| 60 | MES → WMS | `POST /integration/pick-requests` | `no + version` |
| 61 | MES → WMS | `POST /integration/production-inbound` | `no + version` |
| 62 | MES → WMS | `POST /integration/inspections` | `no + version` |
| 63 | WMS → MES | 回调（对方提供地址） | 我方 `txn_id` |
| 64 | WMS → ERP | 回调（对方提供地址） | 我方 `txn_id` |

---

## 3. 核心接口契约

> 只列**实现前必须对齐**的接口；其余接口按第 2 节路径 + 1.1 约定 + 本节同类示例即可推导，字段名与 PRD 第 6 章列名一致。

### 3.1 `POST /auth/login`

请求：
```json
{ "username": "wangjf", "password": "********", "captcha": "a3K9", "remember": true }
```
响应：
```json
{ "code": 0, "trace_id": "t-8f3a...", "data": {
  "access_token": "eyJ...", "expires_in": 7200,
  "refresh_token": "eyJ...", "refresh_expires_in": 604800,
  "user": { "id": 12, "name": "王建峰", "role": "KEEPER",
            "warehouses": [{ "id": 2, "name": "1#原料仓" }] },
  "landing": "/p01"
} }
```
错误：`WMS-4001`（字段）、连续 5 次错 `WMS-4221` + `data.locked_until`。

### 3.2 `GET /inventory/products`

查询参数：`name`、`code`、`date_from`、`date_to`、`page`、`page_size`。

```json
{ "code": 0, "data": { "total": 85, "page": 1, "items": [
  { "code": "A3288", "name": "iphone16",
    "spec": ["尺寸 6.1", "屏幕 OLED", "分辨率 2556×1179", "亮度 2000nit"],
    "qty": 320, "unit": "台", "last_inbound_at": "2026-01-27T10:20:00Z" }
] } }
```
> `qty` 为物理库存（含锁定），与 `inventory.qty` 一致；为 0 仍返回并标记 `zero: true`。

### 3.3 `POST /inbound-orders/{id}/scan`

```json
// 请求
{ "client_op_id": "uuid-v4", "box_code": "BOX20260127ABC123456",
  "location_id": 501, "qty": 1, "sn": "SN2026A1B2C3D4E1" }
// 响应
{ "code": 0, "data": { "order_id": 88231, "status": "PARTIAL",
  "scanned": 12, "plan_qty": 100, "duplicate": false } }
```
错误：`WMS-4093`（`data.box_code` 已扫，`duplicate: true`）、`WMS-4092`（单据已作废）、`WMS-4221`（库位类型不匹配，BR-013）。

### 3.4 `POST /ai/locations/recommend`

```json
// 请求
{ "sku_type": "PRODUCT", "sku_id": 1001, "warehouse_id": 2,
  "qty": 100, "pallet_count": 8, "order_id": 88231 }
// 响应
{ "code": 0, "trace_id": "a1b2c3...", "data": {
  "primary": { "location_id": 501, "location_code": "B2-01-03",
    "confidence": "HIGH", "score": 91.4,
    "reasons": ["同物料已有 2 托在此区，集中管理",
                "距打包区 12m，低于同层均值 18m",
                "剩余容量 40%，可容纳本次 8 托"] },
  "alternatives": [
    { "location_id": 488, "location_code": "A1-02-05", "score": 86.2, "note": "同物料区，容量 15%" },
    { "location_id": 512, "location_code": "B2-02-01", "score": 81.0, "note": "空库位，距打包区 26m" }],
  "degraded": false } }
```
- 置信度按 Top1−Top2 分差：≥8 高、3–8 中、<3 低；**低置信度 `primary` 为 `null`**，只返回 3 个并列候选（AC-AI-03）。
- `degraded: true` 表示坐标缺失导致距离维度权重置 0（PRD 7.7），此时 `reasons` 只有 2 条。
- 采纳后必须调 3.9 `/ai/feedback`，否则采纳率统计不到。

### 3.5 `POST /ai/picking/optimize`

```json
// 请求
{ "order_id": 88302, "order_type": "SALES",
  "points": [ { "location_code": "A1-01-02", "qty": 20 },
              { "location_code": "B2-01-03", "qty": 20 } ] }
// 响应
{ "code": 0, "data": {
  "sequence": ["A1-01-02", "B2-01-03", "C1-03-02"],
  "distance_m": 340, "baseline_m": 520, "saved_m": 180, "saved_pct": 35,
  "algorithm": "HELD_KARP", "point_count": 12, "elapsed_ms": 13 } }
```
- `algorithm` ∈ `HELD_KARP`（≤12 点）/ `NN_2OPT`（13–50）/ `CLUSTER_S`（>50），与 ADR-005 一致。
- 温控/危品约束下 `sequence` 满足「先普货后危品」，AI 只在其内部优化。

### 3.6 `POST /ai/checks/{order_type}/{id}`

`order_type` ∈ `INBOUND` / `OUTBOUND` / `STOCKTAKE`。

```json
// 响应
{ "code": 0, "data": {
  "summary": { "pass": 3, "warn": 1, "block": 0, "timeout": 0, "skipped": 1 },
  "submittable": true,
  "results": [
    { "rule": "R1", "level": "WARN", "title": "数量偏差 12%",
      "detail": "实收 112，计划 100，偏差 +12%，阈值 10%",
      "actions": ["VIEW_DIFF", "FILL_REASON"] },
    { "rule": "R4", "level": "PASS", "title": "超收比例 0%" },
    { "rule": "R5", "level": "SKIP", "title": "可用库存校验",
      "detail": "不适用于入库单，跳过且不计入通过数" }
  ],
  "cache_hit": false, "elapsed_ms": 812 } }
```
- `submittable = false` 当且仅当存在 `BLOCK` 级（BR-017）；此时 3.4 / 3.5 的 submit 接口必须返回 `WMS-4221` 并带 `data.blocking_rules`。
- `level` ∈ `PASS` / `WARN` / `BLOCK` / `LOG`（R6 记录级）/ `SKIP` / `TIMEOUT`。
- 结果缓存 `check:{order_type}:{id}:{version}` 5 分钟；单据版本变化即失效。

### 3.7 `POST /ai/query`

```json
// 请求
{ "question": "上周 A3288 出了多少台？" }
// 响应
{ "code": 0, "data": {
  "conclusion": "上周 A3288 共出库 1240 台，环比前一周 +18%",
  "table": { "columns": ["日期", "出库数量", "单据数"], "rows": [
    ["2026-01-19", 180, 12], ["2026-01-20", 210, 15]] },
  "caliber": "按已出库单据的实际出库数量汇总，不含待出库",
  "metric": "outbound_qty", "sql": "SELECT DATE(created_at) d, SUM(-qty_delta) q ...",
  "row_count": 7, "updated_at": "2026-01-27T09:00:00Z",
  "degraded": false } }
```
- 未命中语义层模板时：`code: 0` + `data.metric: null` + `conclusion: "该口径暂无数据，已记录待补充模板"`，**不得由 LLM 现编 SQL**（ADR-006）。
- `degraded: true` = LLM 超时，只返回 `table` + 模板文案「已为你查到以下数据」。
- 每次调用写 `nl_query_log`（含 `rejected` 标记）。

### 3.8 `POST /sync/push`

```json
// 请求（按 created_at 升序，单次 ≤ 50 条）
{ "ops": [
  { "client_op_id": "uuid-1", "op_type": "INBOUND_SCAN",
    "path": "/inbound-orders/88231/scan", "body": { "...": "..." },
    "created_at": "2026-01-27T10:20:00Z" },
  { "client_op_id": "uuid-2", "op_type": "STOCKTAKE_COUNT", "...": "..." } ] }
// 响应（逐条，顺序与请求一致）
{ "code": 0, "data": { "results": [
  { "client_op_id": "uuid-1", "status": "OK", "http_code": 0 },
  { "client_op_id": "uuid-2", "status": "DUPLICATE", "http_code": "WMS-4091" },
  { "client_op_id": "uuid-3", "status": "FAILED", "http_code": "WMS-4222",
    "message": "可用库存不足，缺口 24" } ] } }
```
- 单条失败**不影响**后续条目（BR-012 冲突以服务端为准）。
- APP 侧对 `FAILED` 标红、`DUPLICATE` 直接删本地、`OK` 删本地。

### 3.9 `POST /ai/feedback`

```json
{ "client_op_id": "uuid", "suggestion_id": 4521,
  "action": "ACCEPT", "reason": null }
```
`action` ∈ `ACCEPT` / `REJECT` / `REVOKE`；`REJECT` 时 `reason` 必填（不合适/不信任/太慢）。写 `ai_feedback`，是 X05 采纳率的唯一来源。

---

## 4. 集成接口契约（MES / ERP）

### 4.1 认证（6.2 签名）

```
X-App-Key: mes-prod
X-Timestamp: 1769498400        # 秒级，偏差 > 300s 拒绝 → WMS-4011
X-Sign: hex(hmac_sha256(app_secret, app_key + timestamp + body_raw))
```
同一 `no + version` 重复推送返回首次结果 + `code: WMS-4091`，不产生重复单据。

### 4.2 `POST /integration/inspections`（MES → WMS 检验任务）

```json
{ "no": "JY20260127001", "version": 1,
  "supplier_code": "GYS-ZTE-001", "logistics_no": "WL20260127001",
  "plate_no": "京A12345",
  "items": [ { "material_code": "BAT-LIPO-4500-003", "plan_qty": 500 } ] }
```

### 4.3 `POST /integration/outbound-orders`（MES → WMS 销售发货指令）

```json
{ "no": "SO20260127001", "version": 1,
  "sales_order_no": "XSDD20260127001", "product_code": "A3288",
  "plan_qty": 20, "delivery_date": "2026-01-28" }
```

### 4.4 `POST /integration/production-inbound`（MES → WMS 完工入库）

```json
{ "no": "PI20260127001", "version": 1, "task_no": "RWD20260127001",
  "box_code": "BOX20260127ABC123456", "product_code": "A3288", "qty": 100 }
```

### 4.5 `POST /integration/pick-requests`（MES → WMS 领料需求）

```json
{ "no": "PL20260127001", "version": 1, "task_no": "RWD20260127001",
  "items": [ { "material_code": "DSP-AMOLED-67-FULL", "qty": 120 } ] }
```

### 4.6 回传（WMS → MES / ERP）

由对方提供回调地址，我方配置在 `sys_config`。载荷示例（入库完成回传 MES）：

```json
{ "biz_no": "PI20260127001", "txn_id": 99001, "actual_qty": 100,
  "location_code": "B2-01-03", "finished_at": "2026-01-27T10:20:00Z" }
```
重试策略：3 次，退避 50 / 200 / 800ms，全失败进重试队列并告警；每日 02:00 对账兜底（`reconcile_diff`）。

---

## 5. 限流与降级

| 对象 | 限流 | 超限行为 |
|---|---|---|
| LLM 调用（问数 / 归因） | 60 次/分钟/用户 | `WMS-4290`，前端提示稍后重试 |
| `/ai/query` | 全局 300 次/分钟 | 降级返回「系统繁忙」 |
| `/sync/push` | 单次 ≤ 50 条，用户级 10 次/分钟 | 分批引导 |
| 普通写接口 | 用户级 600 次/分钟 | `WMS-4290` |
| 集成接口 | 按 app_key 1000 次/分钟 | `WMS-4290` + 告警 |

**降级开关**（PRD BR-020，管理员在规则配置里改，立即生效不重启）：
- `ai_enabled = false` → 52 / 53 返回 `degraded: true` + 系统默认库位/顺序，54 返回全 PASS
- `query_enabled = false` → 55 返回 `WMS-4221`「问数功能已关闭」，前端隐藏 X01 入口
- LLM 不可用 → 55 返回 `degraded: true`（仅数据表），52 / 53 / 54 完全正常（本地规则）

---

## 6. 待确认事项

| # | 事项 | 影响 | 当前处理 |
|---|---|---|---|
| I-01 | MES / ERP 回调地址与字段由对方提供，`sys_config` 配置项名需与对方约定 | 63 / 64 | 按 4.6 实现，地址留配置 |
| I-02 | `sys_config.scope` 的 GLOBAL / SUPPLIER 两级是否够用（供应商级超收阈值已覆盖） | 47 / 51 | 按两级实现，不够再加 WAREHOUSE 级 |
| I-03 | 标签打印走「服务端生成 PDF」还是「浏览器直连打印机」 | 46 | 两端都实现，客户端可选 |
| I-04 | 集成端签名是否改用 OAuth2 client_credentials | 4.1 | 先按 HMAC，改造只影响中间件 |
