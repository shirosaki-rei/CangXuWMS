# WMS 仓储管理系统

FastAPI + MySQL 8 + Redis + Vue3 单机部署。文档与代码的对应关系见下表。

| 目录 | 内容 |
|---|---|
| `docs/` | PRD、架构设计、接口契约、开发任务清单、**分批次执行任务表** |
| `backend/` | FastAPI 服务（api / service / domain 分层） |
| `frontend/` | Vue3 + Vite + Element Plus + Pinia 管理端 |
| `nginx/` | 静态托管 + 反代配置 |
| `tools/` | E2E 冒烟脚本（Chrome CDP） |

---

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
cp backend/.env.example backend/.env      # 已默认建好，改 JWT_SECRET 即可
docker compose up -d --build
```

启动顺序由 healthcheck 保证：`mysql → redis → migrate(建表+种子) → api → worker → nginx`。
访问 http://localhost:8080 。

### 方式二：本地开发

```bash
# 后端
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
./.venv/Scripts/python.exe -m alembic upgrade head              # 建 30 张表
./.venv/Scripts/python.exe -m app.seed                          # 种子数据
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload     # :8000

# 前端
cd frontend
npm install
npm run dev                                                      # :5173，/api 已代理到 8000
```

没有 MySQL/Redis 也能跑：把 `backend/.env` 的 `DB_URL` 改成 `sqlite:///./dev.db`，
Redis 连不上会自动退化到进程内实现（仅单进程开发可用，生产必须配真 Redis）。

### 种子账号（密码同用户名）

| 账号 | 角色 | 可见仓库 |
|---|---|---|
| `admin` | 系统管理员 | 全部 |
| `supervisor` | 仓库主管 | 全部 |
| `wangjf` | 仓管员 | WH-001、WH-002 |
| `liq` | 检验员 | WH-001 |
| `mes-prod` | 集成账号 | 全部（无 UI 权限） |

---

## 测试

```bash
cd backend
./.venv/Scripts/python.exe -m pytest                                  # SQLite：147 passed, 2 skipped
DB_URL="mysql+pymysql://wms:wms123456@127.0.0.1:3306/wms?charset=utf8mb4"   ./.venv/Scripts/python.exe -m pytest                                # MySQL：149 passed, 0 skipped
node ../tools/e2e-smoke.mjs /tmp/e2e                                  # 浏览器全链路（需先起前后端）
```

- 单测默认用 SQLite 文件库，零外部依赖；
- 需要真实行锁的用例打了 `requires_mysql` 标记，**只在 `DB_URL` 指向 MySQL 时执行**
  （10 线程库存守恒、并发下可用量不被击穿）。**这两个用例必须在 MySQL 上跑过一遍**——
  它们验证的是 `SELECT ... FOR UPDATE`，SQLite 没有行锁；
- 建库：`mysql -uroot -p -e "source tools/setup-mysql.sql"`（建 `wms` 库 + `wms` 写账号 +
  `wms_ai_ro` 只读账号），然后 `alembic upgrade head && python -m app.seed`；
- **跑测试会清空数据库**（每个用例前后 `DELETE FROM` 全表），跑完记得重新 `python -m app.seed`；
- 写测试时**不要硬编码主键 id**，用 `tests/conftest.py` 里的 `wh1_id` / `wh1_location_id` /
  `admin_id` 夹具按编码查——SQLite 自增归零会让写死的 id 恰好成立，MySQL 上静默跑错；
- 各域模块带 `python -m app.domain.machine|rules|stock` 自检入口。

---

## 代码结构

```
backend/app/
├── main.py              # FastAPI 实例、中间件、路由挂载
├── core/
│   ├── config.py        # pydantic-settings
│   ├── errors.py        # 错误码表（接口文档 1.2）+ 统一异常处理
│   ├── security.py      # bcrypt / JWT / 图形验证码 / 黑名单
│   ├── deps.py          # db session、当前用户、角色权限、数据权限注入
│   ├── permissions.py   # 权限矩阵（PRD 3.2），前后端共用
│   ├── redis.py         # Redis 客户端 + 进程内兜底
│   └── db.py            # 写连接 / 只读连接
├── api/v1/              # auth / base_data / admin
├── domain/
│   ├── models.py        # 30 张表（架构 6.2）
│   ├── enums.py
│   ├── machine.py       # 5 类单据状态机
│   ├── stock.py         # 库存增减唯一入口（行锁 + 流水）
│   └── rules.py         # BR-008/013/014/025 等纯规则
├── middleware/          # trace_id 贯穿 + 幂等
├── service/             # auth / base_data / admin
└── seed.py              # 种子数据（幂等，可重复执行）
```

---

## 关键约定

1. **响应体四字段固定**：`{ code, message, data, trace_id }`。业务错误 HTTP 仍为 200，
   只有传输/认证层才用 4xx/5xx（接口文档 1.2）。
2. **写操作必须带 `X-Client-Op-Id`**。前端请求封装自动生成；重复提交返回首次结果
   （`code=WMS-4091`）。`op_log` 表是幂等的最终判据。
3. **数据权限在依赖注入层强制注入**，不接受前端传 `warehouse_id` 绕过。
4. **库存只能走 `domain/stock.py`**，任何地方不得直接 `UPDATE inventory`。
5. **状态推进只能走 `domain/machine.py`**，service 不得直接赋 `status`。

---

## 已登记的取舍

见 `docs/WMS分批次执行任务表.md` 第 3 章。要点：
不建 role/permission 表（矩阵是代码常量）、暂不建 repository 层、
30 张表由一个 `create_all` 迁移建、枚举列用 `VARCHAR + CHECK`、
`client_op_id` 只认 Header 不读 body。

---

## 关于默认口令

仓库里的 `wms123456` / `ro123456` / `mes-secret-change-me` 是**本地开发默认值**，
在 `backend/.env.example`、`tools/setup-mysql.sql`、`app/core/config.py` 默认值、
`docker-compose.yml` 默认值四处保持一致，只为让新人 `docker compose up` 能一把跑起来。
真实的 `backend/.env` 已被 `.gitignore` 排除，不会进仓库。

**上生产前必须改**：`backend/.env` 里的 `JWT_SECRET`（≥32 位随机串）、
`MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`，以及 `api_client.app_secret`。
