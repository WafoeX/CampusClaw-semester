# 班级 MCP 集成验收记录

变更：`add-class-mcp-tool-integration`，验收日期：2026-10-22。
本记录区分真实隔离容器、受控 HTTP 测试与部署验收；不声称已核验课程课件全文。
完整规约见 `openspec/changes/add-class-mcp-tool-integration/specs/`（六份、43 个 Scenario）。

## 实际执行与结果

以下命令均在仓库根执行；子项目命令注明目录。未直接读取、展示或改写真实 `.env`；仅在取得演示部署授权后允许 Docker Compose 自动加载配置，并在内存中检查令牌非空与一致性，只输出布尔值。
`TEST_DATABASE_URL` 使用独立测试 PostgreSQL，测试按独立 schema 创建/清理，不指向演示库。
`MCP_TEST_IMAGE=campusclaw-apitest-mcp:local`，仅测试用合成运行时凭证，不在此记录其值。

| 命令/检查 | 实际结果 |
|---|---|
| `cd api && uv run pytest -q --tb=short`，设置隔离 `TEST_DATABASE_URL` | 385 passed；覆盖率 88.83%；1 条既有 Starlette 弃用警告，无测试跳过 |
| `cd mcp-server && uv run pytest -q --tb=short`，设置 `MCP_TEST_IMAGE` | 42 passed，含真实镜像临时容器检查；1 条框架弃用警告 |
| `cd api && uv run ruff check src tests` / `ruff format --check src tests` / `uv run mypy` | 全部通过，109 文件 |
| `cd mcp-server && uv run ruff check .` / `ruff format --check .` | 全部通过，6 文件 |
| `cd frontend && npm run quality` | ESLint、TypeScript、79 项组件/解析器测试、生产构建全部通过；修正重复夹具 ID 后无 React key 警告 |
| `api/.venv/bin/python -m pytest tests --no-cov -q` | 6 passed（已有根目录静态/文档/端口变异测试） |
| `api/.venv/bin/python -m unittest apitest.tests.test_harness apitest.tests.test_clients apitest.tests.test_stub apitest.tests.test_cases -q` | 24 项支持层测试通过；其中故意失败/空套件的报告自测按预期保留非零退出码 |
| `api/.venv/bin/python -m apitest.check_types` | 30 批严格 mypy，0 失败；无排除案例 |
| `api/.venv/bin/ruff check --config api/pyproject.toml apitest` / `ruff format --check --config api/pyproject.toml apitest` | 全部通过，44 文件 |
| `docker compose --env-file /dev/null -f docker-compose.apitest.yml build` / `up -d --wait` | 独立镜像构建及健康启动通过；修正 health 漏识别 MCP 迁移 0007 的接点并补回归 |
| 同一独立 Compose `run --rm --no-deps apitest python -m unittest apitest.tests.stack_checks -v` | 6 passed，含真实 MCP、无默认外网路由、只读 reader 权限 |
| 同一独立 Compose `run --rm --no-deps apitest` | 29/29 正式 URL/方法操作通过，退出 0，HTML 被 Git 忽略 |
| 切换 `APITEST_GENERATION_MODEL=fixture-malformed` / `fixture-failure` 后分别执行消息操作 | 各 1/1 通过；工具 ok、生成 error、历史/SSE/审计一致；已恢复默认 fixture-delayed |
| `node apitest/browser_swagger.mjs` | 真实 Chromium 点击登录/Authorize/登记/连接/发现/技能保存通过；仅用户 JWT，无 MCP 凭证；0 浏览器错误，0 外部请求 |
| `cd frontend && npx playwright test --trace off --timeout 90000 --reporter=json`，连接隔离网关及合成账户 | 原有全部 8 项通过，0 跳过，0 flaky；首次默认 30 秒运行有 1 项全流程超时，未删除或放宽断言，重跑仅延长运行时限 |
| `openspec validate --all --strict` | 6 项全部通过（含前序变更）；有既有长 requirement 的建议提示 |
| 活跃 LSP 检查本轮 25 个前后端/验收文件 | 22 clean、2 文件附带 3 条已核实误报、1 push-only 服务无法确认 clean；不是声称全部由 LSP 证明无误，另有严格 tsc/mypy 验证 |
| 获准主部署 `docker compose --env-file .env build api web mcp-demo` / `up -d --wait db migrate seed api web mcp-demo` | 已先受限备份数据库，构建/迁移/健康启动通过；没有删除/降级已有数据 |
| `docker compose --env-file .env exec -T api python - --protocol < tests/check_mcp_demo.py` | 实际 MCP health、401、Bearer 初始化/发现、100 cm → 1 m 全部通过 |
| `docker compose --env-file .env run --rm --no-deps -T seed python - < tests/check_mcp_demo.py` | 正常 HTTP 登录、主机发现、绑定/发布、工具 ok、SSE/历史/审计一致、断开后 denied、旧 ok 保留均通过；验收智能体已取消发布 |
| `tests/check_mcp_demo.py` 的 Ruff/格式/严格 mypy/活跃 LSP；最终文档链接与 diff 检查 | 全部通过，LSP 1 文件 0 诊断，7 个本地文档链接存在；43/43 Scenario 标题齐全；收尾后源码令牌模式复扫通过 |
| 实际运行容器令牌一致性与无泄漏扫描 | 非空且 API/MCP 一致；316 个源码文件、257 个 index 对象及 HEAD、3 个前端文件、17 个 HTML 报告、演示日志、3 类部署镜像历史/层未发现实际令牌模式；46 个镜像归档成员中解压检查 25 个 gzip，0 未支持压缩；报告与备份被 Git 忽略 |

Docker Desktop 的 internal-only 网络未直接绑定可访问的宿主 loopback 端口；真实浏览器与旧 E2E 使用已核对项目标签的短生命周期 loopback → docker exec/nc → **同一测试 gateway** 桥接，结束即关闭。未给容器增加外网网络，未映射 API/DB；不将桥接结果宣称为原生端口绑定通过。

LSP 辅助误报处置：Python 项目明确要求 3.12，`importlib.resources` 无需兼容 Python <3.7；HTTP 仅用于本机隔离验收；独立测试 CLI 的固定无内容 console 成功句不是生产日志。另核实 Observer 的 `LiteralString` 与分离参数 SQL 和 `__exit__(*args)` 有效清理协议；未放宽运行时检查。

## 提交前复核

本次整理保留原实现，不额外重构；下列结果独立于上面的历史端到端验收：

- 新建独立临时 PostgreSQL 容器运行后端全部测试：385 passed，覆盖率 88.83%，1 条框架弃用警告；测试后删除临时容器及其匿名卷，不使用演示数据库。
- MCP 协议与现有 `campusclaw-mcp-demo:local` 镜像检查：42 passed，1 条框架弃用警告。未重新构建镜像。
- 前端 `npm run quality`：ESLint、TypeScript、79 项测试及生产构建通过。
- 后端 Ruff、格式及严格 mypy 通过；MCP Ruff 与格式通过。MCP 子项目未配置/安装 mypy，本次不增加依赖或宣称其 mypy 通过。
- 根目录静态测试 6 passed；API 验收支持层单元测试 24 passed；验收代码 Ruff、格式及 30 批严格 mypy 通过。
- `openspec validate --strict --all`：6 项通过，保留既有长 requirement 建议提示。
- 初次未配置测试数据库时，后端 272 passed、113 skipped，覆盖率 79.72% 未达门槛；因此补跑上述独立数据库完整测试，不将首次结果视为完整验证。
- 本次未重跑独立 Compose 的 29 项 HTTP 操作、浏览器 Swagger、Playwright E2E 或真实部署问答；这些范围仅保留前述历史记录，不视为本次重验。

## 真实断开观察

测试专用 Compose 为实际 `mcp-demo` 启用仅方法/路径/状态的访问行，不记录正文、参数或授权头；主部署仍禁用访问日志。

1. 建立真实连接并完成有资料的首轮调用，正对照观察到 **4 次 POST /mcp**（initialize、initialized、tools/list、tools/call）。
2. 教师断开后在同一会话再次提问，流/assistant/审计均为 `denied/server_disconnected`，普通资料回答继续。
3. 再次读取实际容器访问行计数，新增 MCP POST **0**；不是仅凭 denied 审计推断未发网络请求。

观察仅针对本次受控执行，不承诺远端分布式 exactly-once。迟到响应、断开竞争、取消/恢复等并发边界另由 PostgreSQL＋受控 HTTP 测试验证。

## Scenario 覆盖矩阵

“已通过”须结合下列证据层理解，受控 HTTP 不冒充真实远端验收。演示/安全项也有独立实际检查，不把隔离替身当作现有部署验证。

证据简写：

- **绑定**：`api/tests/test_skill_tool_bindings.py`、`test_skill_tool_fields.py`；正式 `apitest/cases/api/skills/POST.py`、`{skill_id}/PATCH.py`。
- **执行**：`api/tests/test_mcp_execution.py`、`test_mcp_chat.py`（真实 PostgreSQL、受控 HTTP）。
- **主机**：`api/tests/test_mcp_api.py`、`test_mcp_client.py`、`test_mcp_config.py`、`test_mcp_repository.py`。
- **协议**：`mcp-server/tests/test_protocol.py`、`test_container.py`、`test_deployment.py`。
- **真实 API**：`apitest/cases/api/mcp/` 六项操作与 `api/conversations/{conversation_id}/messages/POST.py`；实际 mcp-demo 容器。
- **前端**：`frontend/src/mcp.test.tsx`、`mcp-outcomes.test.tsx`、`agent-api.test.ts`。
- **Swagger**：`apitest/browser_swagger.mjs`（真实 Chromium/同源网关）与 `api/tests/test_mcp_documentation.py`、`test_openapi_documentation.py`。

### agents/agent-management（6）

| Scenario | 证据与状态 |
|---|---|
| Teacher saves a discovered MCP tool | 绑定＋真实 API＋Swagger：已通过 |
| A binding is inaccessible or unavailable | 绑定＋正式技能 PATCH 的断开 409/回滚：已通过 |
| Tool syntax or count is invalid | 绑定＋正式技能 POST：已通过 |
| Legacy clients omit tools | 绑定＋正式技能 POST/PATCH 的省略/显式空列表：已通过 |
| Teacher selects a tool | 前端＋Swagger：已通过 |
| A saved tool becomes disconnected | 前端保留绑定并显示 409＋真实 API：已通过 |

### conversations/grounded-agent-chat（10）

| Scenario | 证据与状态 |
|---|---|
| A bound skill triggers its tool | 真实 API 的材料问答/ok 审计＋执行：已通过 |
| Two skills reference the same tool | 执行中的去重计划与单次 HTTP 计数：已通过 |
| An old binding is no longer authorized | 执行中的跨班/断开无 HTTP＋真实 API denied：已通过 |
| Tool result contains instructions | 执行中的提示注入/无递归/系统消息隔离：已通过（受控 HTTP） |
| Tool succeeds but no materials support the answer | 真实 API 有工具无资料仍精确拒答＋执行：已通过 |
| MCP fails while ordinary chat is answerable | 执行中 isError/空/非文本/超大/HTTP/超时但回答继续：已通过 |
| Tool call and answer succeed | 真实 API 的 stream/assistant/history/audit 三方核对：已通过 |
| Generation fails after tool execution | 两种真实隔离模型失败模式＋执行：已通过，工具仍为 ok |
| Disconnected tool is used from an existing conversation | 真实 API＋有正对照的远端请求计数观察：已通过 |
| Client disconnects or work times out | 执行中的客户端离开、deadline、迟到 worker、startup recovery：已通过 |

### mcp/class-server-management（11）

| Scenario | 证据与状态 |
|---|---|
| Teacher registers the demo | 主机＋真实 API＋Swagger：已通过 |
| Other roles and classes access management | 主机＋六项真实操作的 401/403/跨班 404：已通过 |
| Registration is invalid | 主机＋正式登记操作的格式/班级字段/URL/重名：已通过 |
| Connection succeeds | 真实 API/Swagger 发现两工具：已通过 |
| Connection fails | 主机＋真实错误令牌服务、受控协议/超时服务返回安全 503：已通过；后两者明确为测试替身 |
| Teacher disconnects a server | 主机＋真实 API 的缓存空列表及请求计数：已通过 |
| Discovery and disconnect race | 主机并发 CAS 测试：已通过（受控 HTTP） |
| A previously dispatched call returns late | 执行中的 connection_invalidated 与丢弃正文：已通过（受控 HTTP） |
| Call succeeds | 真实 API 的本班共享教师审计与只读 SQL：已通过 |
| Call is denied or fails | 执行＋真实断开/错误连接＋审计安全状态：已通过 |
| Audit access crosses a boundary | 执行＋正式审计分页 401/403/跨班过滤 404：已通过 |

### mcp/demo-server（9）

| Scenario | 证据与状态 |
|---|---|
| Initialization and discovery succeed | 协议＋真实 API＋隔离 stack_checks：已通过 |
| Credentials are absent or incorrect | 协议＋真实错误令牌服务＋stack_checks：已通过 |
| Invalid request is submitted | 协议 JSON-RPC 错误/ID/413/415：已通过 |
| Formula hint is requested | 协议＋真实 API 欧姆定律 question：已通过 |
| Unit conversion is requested | 协议＋实际容器 100 cm → 1 m：已通过 |
| Invalid or unsupported arguments are supplied | 协议 schema/有限单位/不使用 eval：已通过 |
| Compose starts the application | 主 Compose 静态边界、独立栈及获准现有演示栈实际构建/迁移/启动：已通过 |
| Health is checked independently | 协议、隔离容器及获准演示容器的 health/Bearer list/call：已通过，不调用模型验证 health |
| Build and frontend artifacts are inspected | 实际令牌模式扫描：跟踪/新文件、Git index/HEAD、部署镜像历史/全部可解码层、前端、日志无命中；已通过（时点性扫描，非任意编码证明） |

### operations/openapi-documentation（2）

| Scenario | 证据与状态 |
|---|---|
| Teacher tries the workflow in a browser | Swagger 的真实点击链：已通过 |
| Error and stream contracts are inspected | Swagger 文档模型测试＋真实 API＋前端严格解析：已通过 |

### testing/api-contract-tests（5）

| Scenario | 证据与状态 |
|---|---|
| End-to-end MCP workflow is tested | 真实 API：29/29 全套，材料问答与审计：已通过 |
| Disconnect is tested | 正式消息操作＋保存 409＋有正对照的 0 新增 POST：已通过 |
| Independent protocol and injection checks run | 42 项协议/镜像测试＋执行注入/迟到测试：已通过；两种证据层不混同 |
| Full report is generated | 29/29 时间戳 HTML、报告忽略和失败退出码自测：已通过 |
| Secret or deployment checks are recorded | 浏览器、只读权限、合成令牌分离、获准演示部署和实际令牌扫描：已通过，证据只保留布尔值/计数 |

## 无秘密证据索引

以下运行产物被 Git 忽略，不承诺全新克隆已带有这些文件；可按命令重建。

- `apitest/reports/20261022T064433875512Z.html`：29/29 完整正式报告。
- `apitest/reports/mcp-invalid-output.html`、`mcp-provider-failure.html`：各 1/1 生成失败补充报告，不冒充完整套件。
- `apitest/artifacts/mcp-swagger.png`、`mcp-browser.json`：清理敏感面板后的真实 Swagger 证据和布尔断言。
- `apitest/artifacts/mcp-disconnect-observation.json`：正对照与断开后的最小请求计数。
- `apitest/artifacts/mcp-demo-smoke.json`：获准现有演示部署的无秘密检查结果。
- `apitest/artifacts/mcp-security-scan.json`：实际运行时令牌扫描范围、计数与限制。
- `tests/check_mcp_demo.py`：可复用的真实部署协议/HTTP 工作流检查源文件；不含凭证。

## 部署经过与验证限制

- 8.2 首次检查因令牌为空暂停，未改动演示栈。用户明确授权后手动配置令牌并要求继续，复查非空与一致均为 true，再完成部署/验收；没有展示或改写真实 `.env`，没有生成替代用户配置的令牌。
- 演示问答实际返回 `insufficient_evidence` 及精确拒答，工具为 ok；断开后的相同会话下一轮为 denied，历史 ok 未篡改。**这不是有证据回答成功或真实模型质量达标的证明**；有同班资料的回答闭环在独立实际 MCP＋确定性模型替身栈中验证。新增验收智能体已取消发布，服务器最终断开，历史和最小审计保留。
- 8.3 首次扫描发现 `backups/` 未被忽略（原规则只有 `backup/`），已补齐根目录忽略并复查。数据库备份权限受限，不作为可公开预览证据；不得提交或分享备份。
- 安全扫描只针对当时实际 MCP 令牌的原文、Base64、URL 编码、JSON 转义模式，不证明任意编码不存在泄漏，不覆盖所有历史 Git 对象，也不对拥有 Docker 主机管理权限者隐藏运行时环境。
- 真实模型质量、未取得的课件全文、任意外网/完整 MCP SDK 互操作、远端写工具均未验收，也不属于本次承诺。
