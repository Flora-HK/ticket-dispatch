# Backend · Dispatch Desk

FastAPI 后端负责认证、RBAC、工单状态机、派发策略、PostgreSQL 事务、幂等、通知、时间线与审计。

项目总览、完整启动流程和测试基线以 [根 README](../README.md) 为准；本文只说明后端目录边界和常用命令。

## 目录职责

| 路径              | 职责                                               |
| ----------------- | -------------------------------------------------- |
| `app/api/routes/` | HTTP 路由、依赖注入、状态码和 OpenAPI 响应         |
| `app/api/deps.py` | JWT、ActorContext、幂等键和角色依赖                |
| `app/services/`   | 创建、派发、接受、拒绝、完成、关闭、重开和治理用例 |
| `app/core/`       | 配置、数据库、安全、统一错误、初始化和演示数据     |
| `app/models.py`   | SQLModel、请求/响应模型、枚举与数据库约束          |
| `app/alembic/`    | PostgreSQL 迁移和 AuditLog 不可变 Trigger          |
| `tests/`          | API、模型、迁移、并发、事务和 OpenAPI 契约测试     |

## 本地运行

以下命令假定已按根 README 完成 Docker、`.env` 和依赖准备。

```powershell
Set-Location E:\Projects\ticket-dispatch
uv sync --package app

Set-Location .\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe app\initial_data.py
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：

- API：<http://localhost:8000/api/v1>
- Swagger UI：<http://localhost:8000/docs>
- 存活检查：<http://localhost:8000/api/v1/health/live>
- 就绪检查：<http://localhost:8000/api/v1/health/ready>

## 数据库与迁移

数据库固定使用 PostgreSQL。测试库与开发库必须隔离，不能改用 SQLite 替代 PostgreSQL 并发和 Trigger 验证。

创建迁移：

```powershell
Set-Location E:\Projects\ticket-dispatch\backend
..\.venv\Scripts\alembic.exe revision --autogenerate -m "describe_change"
```

升级并检查模型漂移：

```powershell
..\.venv\Scripts\alembic.exe upgrade head
..\.venv\Scripts\alembic.exe check
```

## 关键业务约束

- JWT 不携带角色，授权时从数据库加载最新角色。
- 工单状态只能通过显式 action 接口变化。
- 派发锁顺序为“幂等锁 → Team 建议锁 → Ticket 行锁”。
- 同一 Ticket 最多存在一条 `ASSIGNED` 或 `ACCEPTED` Assignment。
- 关键写请求要求 `Idempotency-Key` 和适用的期望版本。
- 业务写入、通知、审计和幂等结果在同一事务中提交。
- AuditLog 禁止应用修改和删除；数据库 Trigger 是最终边界。
- 业务时间线只输出脱敏摘要，不暴露原始审计 detail。

## 质量门禁

```powershell
Set-Location E:\Projects\ticket-dispatch\backend
..\.venv\Scripts\ruff.exe check app tests
..\.venv\Scripts\ty.exe check --python ..\.venv --project . app
..\.venv\Scripts\pyright.exe --pythonpath ..\.venv\Scripts\python.exe app
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\alembic.exe check
```

OpenAPI 契约快照位于 `tests/contracts/openapi.json`。修改公开 API 后，应同步更新契约测试与前端生成客户端。
