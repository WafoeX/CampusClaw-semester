# Task 8：隔离 API 测试框架验证

变更：`add-class-agent-chat-and-api-testing`，schema：`spec-driven`。
本轮仅完成 **8.1–8.6**，整体 **45/60**。Task 9、10 保持未完成，不归档。

## 实现与证据

| 任务 | 实现 | 验证 |
| --- | --- | --- |
| 8.1 | `apitest/run_all.py` 稳定发现大写 method 脚本，验证 URL/方法注册；参数名不同的重复路径也拒绝 | 自测覆盖稳定顺序、非法文件名、错误注册、重复操作、导入失败 |
| 8.2 | 标准库 standalone HTML、HTML 转义、统计/时长、失败继续、非零退出；固定诊断词汇脱敏，导入/执行 stdout 与 stderr 丢弃 | 通过/失败/异常/SystemExit/空套件、敏感异常与打印、token 形状标签、转义、100 条上限均通过 |
| 8.3 | `.gitignore` 忽略 reports、artifacts、`.runtime` | 生成 HTML 后 `git check-ignore` 返回 0；报告不出现在 status，框架源码仍可见 |
| 8.4 | 内部 OpenAI-compatible 替身提供固定 8 维嵌入、引导 JSON、单轮 JSON、拒答、无效 JSON 与 503 fixture | 契约自测禁用 socket.connect 后全部通过；真实栈完成索引、检索和带引用 SSE |
| 8.5 | 独立 `docker-compose.apitest.yml`，9 个服务（含 runner profile），迁移/合成 fixture/索引就绪链及只读 reader | API/Web 镜像构建、全新卷 `up -d --wait`、含 runner 的 Compose config、真实支持层验收均通过 |
| 8.6 | 限定网关的 HTTP/Bearer/JSON、严格 SSE 与分块字节解析、run-scoped UUID 名称、只读 PostgreSQL observer | 非测试数据库目标拒绝且不回显；真实登录/检索/SSE/消息落库一致性；reader 写入与密码哈希读取权限拒绝 |

使用说明与复现命令见 [`apitest/README.md`](../apitest/README.md)。
本轮没有新增依赖；框架复用现有镜像内 httpx、psycopg、FastAPI，报告只使用标准库。
现有严格 Pyright 配置加入新包；未放宽现有静态检查规则。

## 真实执行结果

- 隔离 runner 中执行：
  `python -m unittest apitest.tests.test_harness apitest.tests.test_clients apitest.tests.test_stub apitest.tests.stack_checks -v`
  **23 tests / OK / exit 0**，无跳过；其中 19 项无服务自测、4 项真实 Compose 支持层检查。
- 临时（不提交的）`GET /health` 支持层 fixture 经真实 CLI 运行：**1/1 passed / exit 0**，
  同时核对网关 JSON 与 reader `SELECT 1`。报告：
  `apitest/reports/task8-support-smoke.html`，该报告仅证明 runner 支持层 smoke，不代表 Task 9 验收。
- 正式 `apitest/cases/` 当前只有占位文件，直接执行 `python apitest/run_all.py`：
  **empty_suite / exit 1**，并输出时间戳 HTML。框架没有把空套件误报成成功。
- 真实支持层核对：6 个合成账户、2 个班级、两份独立合成事实索引；
  Alpha 检索自身事实成功、对 Beta-only 事实普通拒答；真实 SSE 通过严格解析，
  数据库恰有一条 user 和一条 completed assistant，正文等于增量组装结果且有当前引用。
- reader 非 superuser/CREATEDB/CREATEROLE，无 agents INSERT、public CREATE、
  users.password_hash SELECT 权限；直接 DELETE 亦由 PostgreSQL 拒绝。
- runner `/proc/net/route` 无默认路由；模型替身自测阻止任何 outbound socket 连接。
  没有向真实外部模型发请求。这是测试栈的网络/替身证据，不是任意网络环境的形式化证明。

## 静态与配置检查

以下最终命令均退出 0：

```sh
api/.venv/bin/ruff check --config api/pyproject.toml apitest
api/.venv/bin/ruff format --check --config api/pyproject.toml apitest
api/.venv/bin/mypy --config-file api/pyproject.toml apitest
uvx pyright --project apitest/pyrightconfig.json
uvx pyright --project pyrightconfig.json
openspec validate --all --strict
git diff --check
```

- Ruff 格式检查：11 个 Python 文件；mypy：11 文件无问题。
- 独立及项目全量 Pyright：0 errors / 0 warnings。
- 主动 LSP 对 11 个新增 Python 文件：**clean=11，0 diagnostics**。
- SQL sink 自动提示按误报处理：查询为 `LiteralString`，运行时值独立传 psycopg parameters，
  且有只读事务/只读角色；未添加 inline ignore 或关闭规则。
- OpenSpec：4 项全部通过。既有主 spec 尚未同步的 archive-order INFO 仍在，留给 10.7。

## 隔离与清理

- 固定独立项目 `campusclaw-apitest`；唯一宿主机映射为 **127.0.0.1:18088** 网关。
- 唯一网络 `internal: true`；三个卷均使用测试项目前缀，无 external 卷；
  没有开发/生产卷，也没有 DB/API/Qdrant/替身宿主机端口。
- 首次干净启动暴露 pg_trgm 引导权限问题；已在测试卷初始化 SQL 中由引导管理员创建扩展，
  随后删除仅本轮测试卷并从空卷再次启动成功，未提升 reader/application-owner 的建库权限。
- `down --volumes` 已清理测试项目：**残留容器 0、卷 0、网络 0**。
  临时 `.runtime` 操作 fixture 已删除；Git 忽略的 HTML 证据保留。
- 清理前后原有 5 个运行容器的 ID/名称集合一致。本轮没有调用这些容器的业务接口或数据库，
  没有启动、迁移或部署到现有开发栈。
- 保留已有未提交源码、`.vitest/`、`node_modules/` 等；未 commit / push。

## 验证边界

本轮完成的是框架与支持层，**不是完整黑盒接口验收**：
Task 9 的逐操作脚本、完整报告及权限/失败场景矩阵尚待实现。
未重跑全部后端覆盖率或前端浏览器矩阵，也未宣称 Task 10 回归/部署验收完成。
引导输出通过结构及确定性 fixture 验证，不宣称任意自然语言的语义安全已获证明。
