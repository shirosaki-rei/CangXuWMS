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
| B01-J | `# syntax=docker/dockerfile:1` 从 Dockerfile 删除 | 该行会额外拉 `docker/dockerfile:1` frontend 镜像，网络不稳时直接卡死构建；本用到的都是稳定语法 | 无 |
