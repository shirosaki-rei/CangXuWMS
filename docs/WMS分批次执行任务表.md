# WMS 仓储管理系统 · 分批次执行任务表

| 项目 | 内容 |
|---|---|
| 文档版本 | V1.0 |
| 编写日期 | 2026-10-30 |
| 上游文档 | `WMS开发任务清单.md`（V1.0）、`WMS架构设计文档.md`、`WMS接口文档.md`、`WMS仓储管理系统_PRD_V2.1.md` |
| 划分原则 | ① 与任务清单 `T-<阶段>-<序号>` 双向可追，不新造编号；② 每批次结束有**可运行、可演示、可回归**的增量；③ 保底项优先，`可延后` 项集中挪到 B06 或二期 |

## 0. 批次总览

| 批次 | 名称 | 映射任务 | 净工时 | 出口条件（不过不放行下一批） |
|---|---|---|---|---|
| **B01** | 基建 + 认证权限 + 基础资料 | T-00-1 ~ T-00-11 | 39d ≈ 7.8 人周 | `/health` 通；能登录并带权限访问；仓库/库位/条码/账号 CRUD 可用；`stock.apply` 与状态机单测绿 |
| **B02** | 库存查询 + 采购入库闭环 | T-01-1 ~ T-01-6、T-00-12 | 29d ≈ 5.8 人周 | 一条来料从检验→扫码→上架→提交→回传全链路跑通，库存守恒 |
| **B03** | 出库闭环 + 离线同步 | T-02-1 ~ T-02-5 | 25d = 5 人周 | FIFO 拣货→提交→扣减→回传；`/sync/push` 四种冲突各有用例 |
| **B04** | 库内作业闭环 | T-03-1 ~ T-03-6 | 22d ≈ 4.4 人周 | 盘点→盈亏单据→解锁；移位三扫；APP 作业页补齐 |
| **B05** | AI 四项能力（一期） | T-04-1 ~ T-04-5、T-04-7、T-04-8 | 35d = 7 人周 | 只读账号三道锁落地；推荐/路径/校验/看板可用；问数（T-04-6）进二期 |
| **B06** | 集成、对账、压测、验收 | T-05-1 ~ T-05-9 | 32d ≈ 6.4 人周 | 41 条 AC 全绿；50 TPS 压测通过；备份恢复演练完成 |
| 合计 | | | **182d ≈ 36.4 人周** | |

> 与任务清单第 7 章的关系：B01 = 任务清单第 1 章（P0 基建），B02 = 第 2 章，B03 = 第 3 章，B04 = 第 4 章，B05 = 第 5 章（去掉可延后的 T-04-6），B06 = 第 6 章。`可延后` 项 T-00-12 因 B06 的集成接口依赖它，前移到 B02 末。

## 1. B01 明细（本批次，已执行）

| # | 任务 | 交付物 | 对应 T | 完成标准 |
|---|---|---|---|---|
| B01-1 | 工程骨架：FastAPI 分层（api/service/domain）、pydantic-settings、JSON 结构化日志、统一异常与错误码、trace_id 贯穿 | `backend/app/{main.py,core/*}`、`GET /health` | T-00-1 | 错误码表与接口文档 1.2 逐条对得上；响应体四字段固定 |
| B01-2 | Docker Compose：mysql/redis/api/worker/nginx + healthcheck + 启动顺序 + 卷 | `docker-compose.yml`、`nginx/nginx.conf`、`backend/Dockerfile` | T-00-2 | `depends_on: condition: service_healthy` 链路完整；`docker compose config` 通过 |
| B01-3 | 建表脚本 30 张表 + 索引 + 种子数据 | `backend/alembic/versions/0001_init.py`、`backend/app/seed.py` | T-00-3 | `alembic upgrade head` 一键建库；seed 含仓库/库位/物料/产品/账号，重复执行幂等 |
| B01-4 | 认证：bcrypt、JWT 签发/刷新/登出、图形验证码、5 次错锁 10 分钟、Redis 黑名单 | `backend/app/api/v1/auth.py`、`core/security.py` | T-00-4 | 接口 1–3；锁定/重放/黑名单各一例 |
| B01-5 | 依赖注入层：db session、当前用户、角色权限、数据权限（可见仓库注入） | `backend/app/core/deps.py` + 权限单测 | T-00-5 | 仓管员跨仓查询返回 `WMS-4030`，不接受前端传 `warehouse_id` 绕过 |
| B01-6 | `domain/stock.py`：行锁库存入口、写流水、可用量校验、死锁重试 | `backend/app/domain/stock.py` + 10 线程守恒单测 | T-00-6 | 并发加减后 `SUM(qty)` 守恒；`txn` 条数与操作数一致 |
| B01-7 | `domain/machine.py`：5 类单据状态机 + 终态/作废约束 | `backend/app/domain/machine.py` + 状态机单测 | T-00-7 | 非法迁移抛 `WMS-4221`；终态不可回退 |
| B01-8 | 幂等中间件：`client_op_id` + Redis SETNX + `op_log` 兜底 | `backend/app/middleware/idempotency.py` + 重放测试 | T-00-8 | 同 `client_op_id` 提交 3 次，返回首次结果且 `code=WMS-4091` |
| B01-9 | 前端骨架：Vue3 + Vite + Element Plus + Pinia、路由/布局/请求封装/错误码映射 | `frontend/` 可登录空后台 | T-00-9 | 登录→落地页→菜单→登出全通；401 自动跳登录 |
| B01-10 | 基础资料 CRUD：仓库/库位/条码 + 停用校验（BR-014）+ 条码唯一（BR-009） | 接口 39–46 + P18–P20 页面 | T-00-10 | 停用有库存仓库被拒并列出阻塞项；重复条码返回 `WMS-4093` |
| B01-11 | 账号与权限：用户/角色/数据权限分配 + 权限矩阵页 | 接口 48–51 + 账号/权限矩阵页 | T-00-11 | 改数据权限后立即生效；矩阵与 PRD 3.2 一致 |

### 1.1 B01 内的执行顺序（依赖驱动）

```
B01-1 骨架 ──┬─> B01-2 compose ──> B01-3 建表+seed ──┬─> B01-4 认证 ──> B01-5 deps ──┬─> B01-10 基础资料
            │                                        └─> B01-6 stock ──> B01-7 machine ─┤
            │                                                                           └─> B01-11 账号权限
            └─> B01-9 前端骨架（与后端并行）──────────────────────────────────────────────┘
                                                              B01-8 幂等中间件（依赖 B01-3 的 op_log）
```

### 1.2 B01 验收结果（2026-10-30，MySQL 实测通过）

| 项 | 结果 |
|---|---|
| 后端单测 · SQLite | **147 passed, 2 skipped**（skipped 为 MySQL 行锁用例） |
| 后端单测 · **MySQL 8.0** | **149 passed, 0 skipped** —— 含 10 线程库存守恒、并发下可用量不被击穿 |
| 浏览器 E2E（`tools/e2e-smoke.mjs`，Chrome CDP） | **9/9 通过**：登录页 → 验证码解码 → 登录跳转 → 菜单 → 仓库 3 行 → 库位 40 条 → 权限矩阵 22 行 → 新增仓库 3→4 → 退出回登录页 |
| 服务冒烟 | `/health` `/metrics` 正常；登录/登出黑名单/越权 403/缺幂等键 400 均符合接口文档 1.2 |
| 数据权限 | 仓管员只见 WH-001/WH-002（24 个库位）；显式传 `warehouse_id=3` 返回 `WMS-4030`；未分配仓库的账号列表为空不报错 |
| 只读账号（架构 8.1 第一道锁） | `wms_ai_ro` 可 `SELECT`；`UPDATE` / `INSERT` 均被拒（errno 1142） |
| 前端 | `vue-tsc` 零错误，`npm run build` 通过（dist 约 1.1 MB / gzip 374 KB） |
| 建表 | `alembic upgrade head` 在 MySQL 上一次建成 30 张表；`python -m app.seed` 灌入 76 条，重复执行幂等 |
| 部署 | `docker compose up --build` 全栈起停正常：mysql/redis healthy → migrate 建表+种子 → api healthy → worker → nginx；浏览器 E2E 打 `:8080`（nginx 反代 + SPA history 兜底）9/9 通过 |

#### 实施中修掉的三个真问题

1. **`_MemRedis.incr` 死锁**：`threading.Lock` 不可重入，`incr` 内部调 `get` 自己锁自己 → 改 `RLock`。
2. **SQLite 下 `BIGINT` 主键不自增**：SQLite 的 `BIGINT` 不会成为 rowid 别名，`Base` 加
   `BigInt = BigInteger().with_variant(Integer, "sqlite")`。
3. **测试硬编码主键 id**：`warehouse_id: 1`、`/warehouses/1`、`row.user_id == 1` 在 SQLite 上
   恰好成立（重建表后自增归零，仓库 1 号正好也是库位 1 号），在 MySQL 上全线跑错。
   已改为 `wh1_id` / `wh2_id` / `wh3_id` / `wh1_location_id` / `admin_id` 夹具按编码查 id。
   **教训：这套用例在两种后端上都跑过才算数。**

#### 仍未完成

| # | 事项 | 影响 |
|---|---|---|
| U-02 | ~~Docker 守护进程未启动~~ **已解决**：启动 Docker Desktop 后 `docker compose up --build` 通过。修掉两处 compose 写法错误——`environment:` 里误用 `$$` 转义（变成字面量 `${MYSQL_USER}`）、mysql healthcheck 用 exec 形式导致 `$$` 不被展开（改 `CMD-SHELL`）。另删掉 Dockerfile 的 `# syntax=` 行，它要拉 frontend 镜像，国内网络不稳 |

## 1.3 B02 验收结果（2026-11-03，MySQL 实测通过）

对应 T-01-1~6 + T-00-12。

| 项 | 结果 |
|---|---|
| 后端单测 · SQLite | **221 passed, 2 skipped** |
| 后端单测 · **MySQL 8.0** | **223 passed, 0 skipped** |
| 全链路 E2E（`tools/e2e-b02.mjs`，Chrome CDP） | **17/17 通过**：登录 → 三个库存/流水页 → 取检验单 → 扫码 300 → 判定合格 → 生成采购入库单 → 取库位 → 扫码收货 → 提交落库 → **库存守恒 +300** → 流水结存一致 → 三个页面走查 |
| 前端 | `vue-tsc` 零错误，`npm run build` 通过 |

新增接口：4/5/6/25（库存与流水 + 导出）、7/8/26/27/37（入库单）、11/12/34/35/36（来料检验）、62（MES 推送）。
新增页面：P01/P02/P03/P04、P05–P09（入库列表 + 详情）、P14（来料检验）。

### 实施中修掉的六个真问题

1. **扫码到计划数就把单子推到 `DONE`**，提交时反被「已终态」挡住。改为扫码只推进到 `PARTIAL`，`DONE` 由 `submit` 独占——PRD 第 9 章状态图与接口 27 是两个动作，同时生效会死锁。
2. **`transit()` 的「同态直接返回」写在终态校验之前**，已作废的单能被反复作废。调整顺序并补自检。
3. **作废接口漏了角色守卫**（用了 `CurrentUser`），仓管员也能作废。按 PRD 3.2 加 `inbound:void`。
4. **`over_receive_ratio` 只读 `sys_config`**，没读供应商档案的覆盖值。BR-023 明确覆盖优先，改为先查 `supplier.over_receive`。
5. **`gen-inbound` 的 body 全可选字段却仍要求必须有 body**，空 body 直接被 4001 挡掉。改为 `| None = None`。
6. **`get_order` 查 SKU 编码没按单据的 sku_type 选表**，成品与物料共用自增 id，采购单显示成了成品编码。截图里能直接看出来。

另有两处测试自身的坑：SQLite 重建表后自增归零，让「仓库 id 当库位 id 用」恰好成立，MySQL 上静默跑错；`location_blockers` 原先把全局未结单据都算作本仓阻塞项，改为按明细目的库位归属。

## 2. 批次门禁（DoD，每批次通用）

沿用任务清单第 9 章，另加三条本表专用：

1. 接口路径/参数/错误码与 `WMS接口文档.md` 一致；
2. 涉及 `domain/stock.py`、`domain/machine.py`、`ai/nl_query/guard.py` 的有单测；
3. 对应 AC 可手工验证通过；
4. 无未登记的临时妥协（有就写进架构文档风险表）；
5. **新增**：`docker compose up` 能起全栈（B02 起强制）；
6. **新增**：上一批次的门禁用例全部保留在 `backend/tests/`，不允许注释掉。

## 3. 已知取舍（B01 实施时记录）

| # | 取舍 | 原因 | 升级路径 |
|---|---|---|---|
| B01-A | 不建 `role` / `permission` 表，权限矩阵是代码常量 | 架构 DDL 本就没有这两张表，`user.role` 单角色枚举已覆盖 PRD 3.2 | 需要多角色或自定义权限时再加表，改 `core/deps.py` 一处 |
| B01-B | `repository/` 层暂不建，service 直接查 model | 基础资料 CRUD 无跨表业务逻辑，空目录只是摆设 | 出现「同一次查询被多个 service 复用」时再抽 |
| B01-C | Redis 不可用时退化到进程内 `_MemRedis` | 开发机没起 Redis；多 worker 下不共享 | 生产必须配真 Redis（compose 已含），退化仅限本地 |
| B01-D | 30 张表由一个 `create_all` 迁移建，不做逐表 `op.create_table` | 首版建表，逐表写 600 行迁移无收益 | 从 B02 起改迁移必须用 `op.*`，保证可回滚 |
| B01-E | 枚举列用 `native_enum=False`（VARCHAR + CHECK） | MySQL ENUM 加值要改列，Alembic 难自动生成 | 无 |
| B01-F | `client_op_id` 只认 Header `X-Client-Op-Id`，不读 body 字段 | BaseHTTPMiddleware 提前读 body 会把流耗尽，下游拿不到数据；PC 与 APP 都在我们手里，统一发 Header 即可 | 外部调用方要按 body 传时，改成纯 ASGI 中间件并回放 body |
| B01-G | AI 只读连接池（架构 8.1 第一道锁）未建 | B01 没有 AI 模块，建了只是白开一个连接池 | B05 / T-04-1 与三道锁一起建 |
| B01-H | `sys_config` 的 `SUPPLIER` 级只实现了读写，未接校验规则 | 校验引擎在 B05 / T-04-4 | B05 接入 `check_over_receive` |
| B01-J | 测试用 `truncate_all` 放在 `tests/conftest.py` 而非 `app/core/db.py` | 清数据是测试行为，不该进生产代码；且标识符引号要按方言来（MySQL 不认双引号） | 无 |
| B01-K | `# syntax=docker/dockerfile:1` 从 Dockerfile 删除 | 该行会额外拉 `docker/dockerfile:1` frontend 镜像，网络不稳时直接卡死构建；本用到的都是稳定语法 | 无 |
| B02-A | 扫码收货只推进到 `PARTIAL`，不按 PRD 状态图直接到 `DONE` | 接口 27 定义了独立的「提交入库」动作（落库 + 校验），两个都生效会死锁 | 若产品要求「扫满即完成」，需先去掉 submit 或把它改成可选 |
| B02-B | 导出走同步流式 CSV，没做「任务号 + 轮询」的异步导出 | 日均 800–2000 单下 5 万行 CSV 几 MB，一个请求扛得住；超过 5 万行直接报错让缩小范围 | 出现请求超时再拆异步（B06 接 APScheduler） |
| B02-C | 集成端原始 body 用纯 ASGI 中间件缓存，只对 `/api/v1/integration/` 生效 | BaseHTTPMiddleware 会缓冲整个响应体并吃掉 body；纯 ASGI 只在该前缀动手，其余路由零开销 | 无 |
| B02-D | 提交前校验（X04）未接入 submit | 校验引擎在 B05 / T-04-4；B02 只做落库前的最小校验（库位、差异原因、BR-004） | B05 接入后 submit 前先跑 `check_engine.run()` |
| B02-E | APP 端页面（A02–A05）未做 | T-01-7 的 Expo 骨架在任务清单里但没归入任何批次，见第 4 章 | B03 前补一批 APP 骨架 |

## 4. T-01-7 的归属（B02 复盘时发现的漏洞）

原《WMS开发任务清单.md》第 2 章的 T-01-7「APP 骨架：Expo + RN 导航 + SQLite 队列 + 扫码（PDA 打样放第一周）」估 8d，
在最初分批时漏掉了——它不在 B01–B06 任何一批里，但 B03 的 T-02-2（扫码拣货 A07/A08）和 B04 的 T-03-6
（APP 剩余页 A06/A07/A09）都依赖它。

**处理：前移到 B03 第一周。** 理由：

1. 不补这个洞，B03 的 APP 页面会直接卡住；
2. 任务清单自己标了「PDA 打样放第一周」——工业 PDA 的扫码兼容性是要尽早发现的风险
   （若 Expo 不兼容需退 Expo 或加 config plugin，代价 5–10d），越晚做越贵；
3. B02 的入库闭环已把服务端契约跑通，APP 侧照抄同一套 `client_op_id` 幂等协议即可。

**B03 新增任务**：

| # | 任务 | 交付物 | 对应 T | 完成标准 |
|---|---|---|---|---|
| B03-0 | APP 骨架：Expo + RN 导航 + SQLite 队列 + 扫码（**PDA 打样放第一周**） | `mobile/` 可扫码的空 APP | T-01-7 | 真机扫得出码；离线入队、恢复网络后能补传 |
| B03-0.1 | APP 请求层复用 PC 端同一套幂等协议 | `mobile/src/api` | — | 断网扫码 → 本地队列 → `/sync/push` 逐条返回 OK/DUPLICATE/FAILED |

> **风险前置**：B03 第一周必须出 PDA 打样结论。不兼容就要动技术选型，那是 5–10d 的代价，
> 不能等到 B03 末才发现。
