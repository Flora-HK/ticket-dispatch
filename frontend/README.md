# Frontend · Dispatch Desk

React 前端为 Submitter、Handler、Dispatcher 和 Admin 提供角色化工作区，主视角是 Dispatcher 的派发总览与派发工作台。

项目总览、完整启动流程和测试基线以 [根 README](../README.md) 为准；本文只说明前端结构、配置和浏览器测试。

## 技术结构

- React 19 + TypeScript
- Vite 8
- TanStack Router：页面、URL 搜索参数与路由保护
- TanStack Query：服务端状态、cursor 分页与失效刷新
- Tailwind CSS 4 + Radix UI + shadcn 风格组件
- `@hey-api/openapi-ts` 生成客户端

| 路径                      | 职责                                |
| ------------------------- | ----------------------------------- |
| `src/routes/`             | 页面路由与应用壳                    |
| `src/features/`           | 总览、派发、工单、通知和 Admin 页面 |
| `src/client/`             | OpenAPI 自动生成的服务与类型        |
| `src/components/`         | 通用 UI、应用壳、状态组件和工单组件 |
| `src/hooks/`              | 认证、移动视口和共用逻辑            |
| `tests/`                  | Playwright、axe 和截图捕获          |
| `playwright/screenshots/` | 真实页面截图                        |

## 页面

| 路径                  | 页面                                   |
| --------------------- | -------------------------------------- |
| `/login`              | OAuth2 password flow 登录              |
| `/`                   | 角色化工作总览                         |
| `/dispatch`           | Dispatcher / Admin 派发工作台          |
| `/tickets`            | 工单列表、筛选与创建                   |
| `/tickets/{ticketId}` | 工单详情、评论、时间线、派发历史和动作 |
| `/notifications`      | 当前用户通知                           |
| `/admin/users`        | Admin 用户与角色                       |
| `/admin/teams`        | Admin Team 与成员                      |
| `/admin/audit`        | Admin 只读审计                         |

## 本地运行

先按根 README 启动 PostgreSQL 和 FastAPI，并确认 `frontend/.env` 中的 `VITE_API_URL` 指向后端。

```powershell
Set-Location E:\Projects\ticket-dispatch
bun install

Set-Location .\frontend
bun run dev
```

打开 <http://localhost:5173>。

## 演示数据

后端启动后执行：

```powershell
Set-Location E:\Projects\ticket-dispatch\frontend
bun run seed:demo
```

脚本通过真实 API 幂等创建 Team、多角色账号和覆盖主要状态的工单。Admin 使用根目录 `.env` 中的 `FIRST_SUPERUSER` 和 `FIRST_SUPERUSER_PASSWORD`；其他演示账号及本地凭据由脚本维护，README 不复制密码。

## API 客户端

后端公开 API 固定为 36 个 OpenAPI operations。生成客户端位于 `src/client`，按 tag 生成 `UsersService`、`TicketsService`、`AssignmentsService` 等服务，不在前端手工维护后端 DTO。

配置位于 `openapi-ts.config.ts`。后端契约发生变化时，应先更新 OpenAPI 快照，再重新生成客户端，并提交相应类型与服务差异。

## 交互约束

- 工单动作以服务端 `allowed_actions` 为准，本地角色只控制导航和页面可见性。
- 用户提交时创建新的 `Idempotency-Key`。
- 收到 `409` 后刷新相关查询，不自动重放旧请求。
- cursor 由服务端生成并保持不透明；筛选变化会清空旧 cursor。
- `401` 清理 token 并返回登录；`403`、`404`、`409`、`422` 和 5xx 使用对应状态组件。

## 设计系统

Signal Desk · Signal Ledger 设计系统使用语义颜色、4px 间距网格、低阴影和等宽数字：

- 蓝色表示主操作和当前选择；
- 黄色表示等待；
- 红色表示错误或冲突；
- 绿色只表示完成确认；
- 状态同时使用文字和颜色表达。

页面支持浅色、深色和跟随系统。桌面使用折叠侧栏和高密度数据布局；移动端使用抽屉导航、卡片式信息行和行内主从布局。派发页在桌面为三轨／1024px 双栏，移动端为队列、详情、派发三段流程。

筛选页使用工具条、条件标签和渐进展开的高级筛选；表格只在自身容器内滚动。错误反馈区分 409 冲突、422 字段错误与其他可重试错误，冲突会保留输入并展示刷新前后版本差异。

可访问性实现包括可见标签、图标按钮可读名称、Radix UI 焦点管理、与最终结构一致的 loading skeleton，以及错误和异步区域的语义化提示。axe 自动化扫描覆盖 7 个主要页面的桌面与移动视口。

## 测试

单元测试：

```powershell
Set-Location E:\Projects\ticket-dispatch\frontend
bun run test:unit
```

构建检查：

```powershell
bun run build
```

行为 E2E：

```powershell
bunx playwright test --grep-invert "capture"
```

完整 E2E 与截图捕获：

```powershell
bunx playwright test
```

`tests/visual.spec.ts` 会覆盖 `playwright/screenshots/` 中受 Git 跟踪的图片。只做行为回归时使用 `--grep-invert "capture"`；确需更新作品集截图时再单独运行截图用例。

Playwright 需要可用的 PostgreSQL、FastAPI、演示数据和正确的前端配置。当前测试配置使用浏览器登录态文件，应在受控本地环境中运行。
