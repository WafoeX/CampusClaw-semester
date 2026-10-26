## Why

第 5 课的 CampusClaw 已支持班级隔离、技能修订与流式引导，但技能不能连接真实远端工具。第 6 课需要一个同仓、同 Compose 的 MCP 服务以及可验收的登记、发现、技能调用和审计闭环，同时不破坏已有检索与引用约束。

## What Changes

- 新增 `mcp-server/` 独立容器，提供健康检查、Bearer 保护的 JSON-RPC MCP 子集与 `formula_hint`、`unit_convert` 两个只读工具；主应用通过 `http://mcp-demo:8090` 真实联网调用。
- 教师登记本班服务器名称、Base URL，连接时完成初始化和工具发现，断开时清空缓存；教师界面显示状态、错误与工具名。
- 扩展现有结构化技能的 `tools` 列表，支持 `knowledge_search` 与 `tool@server`；保存校验班级、连接与发现状态，工具绑定进入不可变修订。
- 按用户确认，绑定到当前智能体的有效技能即视为每轮命中；服务端有界、去重调用 MCP，结果仅作为用户消息中的不可信辅助数据，不成为系统指令或独立事实证据。
- 流终态 meta、持久化消息与班级工具审计记录 `tool_calls`，区分 `ok`、`denied`、`error`，断开后明确拒绝而非静默成功。
- 增补 OpenAPI/Swagger、隔离 `apitest/` 真实 MCP 集成与不入 Git 的 HTML 验收报告。
- 令牌仅从本机 `.env` 注入服务端运行时，不接受浏览器提交或回传原始 MCP 密钥，不进入 Git、前端或镜像层。

## Capabilities

### New Capabilities

- `mcp/demo-server`: 同仓演示 MCP 协议服务、两个确定性工具、运行时令牌及 Compose 互通。
- `mcp/class-server-management`: 班级服务器登记、握手发现、连接状态、缓存失效、调用鉴权与最小审计。

### Modified Capabilities

- `agents/agent-management`: 为现有技能增加工具引用列表和保存校验，维持创建者权限与修订语义。
- `conversations/grounded-agent-chat`: 增加服务端工具执行、辅助数据隔离、终态 meta 与历史工具状态；保留资料引用及原 SSE 事件顺序。
- `operations/openapi-documentation`: 补充 MCP 管理、审计、技能及 SSE meta 契约与 Swagger 试调。
- `testing/api-contract-tests`: 增加真实演示 MCP 的隔离端到端验收与失败覆盖。

上述四个已有能力目前只存在于已完成但未归档的 `add-class-agent-chat-and-api-testing/specs/`，尚未同步到主规约。本变更复用其完整路径，以 ADDED Requirements 增补、不复制或改写旧要求；实施和未来同步时必须与前序变更共同核对，不擅自归档历史变更。主规约 `materials/knowledge-retrieval` 不变。

## Impact

- 后端：现有 FastAPI、SQLAlchemy/PostgreSQL、Alembic、httpx；涉及技能修订、对话任务/终态写入、SSE schema、配置与新 MCP 路由/客户端/仓储。
- 前端：教师 MCP 管理和审计入口、技能工具选择、学生工具执行状态；不新增第二个 CampusClaw。
- 部署：新增 MCP 构建上下文、运行时环境变量、内部网络服务；测试 Compose 使用独立 MCP 实例与合成令牌，不使用演示/生产卷或付费模型。
- 兼容：旧技能默认 `knowledge_search`；旧单轮问答不调用 MCP；无工具技能、登录、资料与流式引用流程维持原行为。
- 非目标：技能文件解析/导入、关键词或模型自主路由、写操作工具、任意外网服务器、MCP OAuth/stdio/完整传输实现、多智能体协作、工具结果独立支撑回答。
- 来源限制：已阅读仓库 README、前序规约及相关实现；课程课件链接被抓取工具的 fake-IP 安全检查阻止，未核验全文，课程示范源码本仓不可见。用户已确认按本次提供的完整要求规划；如后续课件产生实质差异，应先修订本变更再实施。
