# 榆梯检点·证书哈希目录

复核工位用证书编号检出归档记录，追查桶分裂及缺失、到期、撤销的证书。

## 业务流程

1. 检证接班
2. 资质卷宗
3. 目录重放
4. 检证与桶证据

Python 依据哈希低位寻址，按局部深度拆桶，必要时倍增目录。

榆梯维保复核组收维保档案员交来的证书卷宗，按点检计划复核编号、失效及撤销状态，再交给维保调度。旧表反复全表找号，导入量上升时桶深不可见，退件与过期无法在同一交接表解释。

08:30 收 YT-1124-东梯检的 9 条证书，08:35 核查编号，08:40 保存 6 条点查项，08:45 设单桶 2 件，08:46 后台插入并重放目录，08:50 核对缺失 1、到期 2、撤销 1，08:55 导出回执和桶证据。

以 SHA-256 前 64 位的低位索引目录，桶局部深度等于全局深度时先扩容目录，再按新增区分位迁移槽位和记录。深度上限为 12，封顶桶允许溢出且显式报告。点查显式返回有效、到期、撤销与未登记，失效日零点起即过期。索引为可重复的 Python 存储实验，PostgreSQL 保存输入、任务及结果。本实验未模拟磁盘页、并发写入与删除后缩容。

## 启动

```sh
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
```

打开 <http://localhost:18254>。OpenAPI 在 <http://localhost:19254/docs>，数据库映射到本机 17754。所有暴露端口只绑定回环地址。Compose 启动 frontend、backend、worker、db、redis，各自通过健康探针检查。数据库、Redis 和共享产物目录各有命名卷；任务状态及导出内容以数据库中的证据为准。

首次启动时幂等载入演示数据。手动载入可运行 `docker compose exec -T backend python -m scripts.seed_demo`。常规停止可用 `docker compose down`。验收环境清理才加 `-v`，它会删除本项目的数据卷。

## 角色与交接

演示账号共用口令 `Demo-DbWorkbench-2026`。

| 登录名 | 角色 | 可执行操作 |
|---|---|---|
| operator | 资料操作员 | 登记业务资料、设置「目标单桶容量」、提交、查看和下载结果 |
| reviewer | 业务复核员 | 查看执行证据、签署单次复核、下载交接单 |
| viewer | 只读观察员 | 查看资料、执行结果及审计，下载证据 |

选用「YT-1124-东梯检」对应的演示资料，保存一份复演资料，再以默认参数 2 提交。worker 保存结果摘要、业务明细和 SHA-256。复核员登录后在「检证与桶证据」签署。

## 开发说明

| 部分 | 实现 |
|---|---|
| 前端 | 原生 HTML、CSS、JavaScript ES Modules、Nginx |
| 后端 | Python 3.11、FastAPI、SQLAlchemy、JWT |
| 数据库 | PostgreSQL 16 |
| 后台执行 | Redis 通知、数据库持久任务队列、行锁与执行租约、Python worker |

从 `backend/src/domain/scenario.py` 修改业务入口和演示口径，运行 `docker compose up -d --build --wait` 查看变更。数据库表结构在 `backend/src/models` 和 `backend/migrations`，输入模型在 `backend/src/schemas`。业务页和请求接口在 `frontend/src/pages`、`frontend/src/api`。资料、执行、复核三个工作流实体各有独立表和 API；场景输入及结果保留在所属资料和批次中。

角色枚举在 `backend/src/constants/roles.py`、`frontend/src/constants/roles.js`，用于服务端访问控制、账号初始化、前端导航与签署。批次状态在 `backend/src/constants/job_state.py`、`frontend/src/constants/states.js`，用于队列、状态 API、状态标记与轮询。登记、提交、领取、接管、完成和签署事件写入审计表。

### 夜间批次的中断恢复与并发收尾

批次在 `queued → running → done/failed` 之间流转，靠数据库执行租约保证夜间长时间检证不丢批、不重复登记完工：

1. **领取**：worker 在一个事务里用 `FOR UPDATE SKIP LOCKED` 选出最早的「排队中」或「运行中但租约已过期」批次，写入本进程标识 `owner` 与 `lease_expires_at`，`attempts` 加一。同一批次同一时刻只有一个进程能领取。
2. **保活**：计算在事务外执行（不长占行锁），后台线程按 `LEASE_SECONDS/3` 的节奏续租；健康进程不会因单批耗时长而被误接管。
3. **接管**：原进程超时、崩溃或仍连着库但租约已过期时，下一拍（最迟约 1 秒）由别的 worker 接管同一批次，记 `reclaim` 审计并清空上一进程的半成品字段后重跑。
4. **收尾 CAS**：终态写入是带 `status=running AND owner=自己 AND lease_expires_at 未变` 条件的 compare-and-swap UPDATE。原进程晚到的成功或报错命中 0 行、被静默丢弃，无法改动已被接管收尾的批次。
5. **完工不重复**：终态字段、`finished_at` 与 `done/failed` 审计事件在同一事务、受同一 CAS 保护，重试只产生一条完工记录。
6. **完成口径**：证据 `result` 与校验摘要 `digest` 在同一条 UPDATE 落库（要么同时可见，要么都不可见）。只有 `done` 且二者齐备时，检证页面才显示完成并开放签核与导出，服务层签核/导出接口同样按此口径拦截。

租约时长由 `LEASE_SECONDS`（默认 30 秒）配置；`runs.owner`、`runs.lease_expires_at`、`runs.attempts` 通过 `migrations/v002_run_lease.py` 在旧库上幂等补齐。多 worker 副本靠同一套行锁与租约协调（水平扩容时需去掉 compose 里 worker 的固定 `container_name`，再用 `docker compose up -d --scale worker=N`）。

`COMPOSE_PROJECT_NAME` 设置栈名，`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT` 设置端口。通过 `DB_PASSWORD`、`JWT_SECRET`、`DEMO_PASSWORD` 配置本地凭据。设置 `SEED_DEMO=false` 可关闭演示数据载入，此时数据库初始没有演示账号。数据库密码调整后，已有数据卷需在数据库内同步修改用户密码。

## 验收范围

在内存计算目录，容量与最大深度可复核。卷宗和证据由 PostgreSQL 持久化。 当前界面用 JSON 编辑业务资料，以 JSON 下载证据。过程和截图保存在批次的 [验收记录](../../test-artifacts/gb-6105/TESTING.md)。

[MIT License](LICENSE)
