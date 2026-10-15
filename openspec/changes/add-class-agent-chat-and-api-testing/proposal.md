## Why

CampusClaw 已具备 Bearer 认证、班级隔离材料检索和带引用的单次问答，但教师无法配置面向本班的解题智能体，学生也没有可持久化、可流式使用的多轮会话。与此同时，主要接口虽由 FastAPI 暴露基础 OpenAPI 信息，仍缺少可验收的认证/错误契约，以及按 URL 组织、同时核对响应与数据库状态的独立接口测试套件。

## What Changes

- 新增班级内多智能体管理：教师可创建多个智能体，配置提示词，维护并绑定技能；智能体先为草稿，显式发布后才可供本班学生选择。
- 至少支持一条“解题引导”类技能，其行为约束为提供思路、步骤与追问，不直接输出最终答案；仅创建者可修改、发布或删除其智能体及技能。
- 新增持久化多轮会话与消息：学生选择本班已发布智能体创建会话；每轮回答受同一会话历史影响，但每次都必须先检索当前用户所属班级的知识库，并仅以重新授权的本班证据支持事实性内容。
- 新增使用 Bearer 认证的 SSE 流式消息接口，输出有类型的元数据、文本增量、引用、完成和安全错误事件；浏览器展示流式状态与可核验引用。
- 保留现有 `POST /api/knowledge/query` 单次、非流式接口及其行为，避免现有调用方破坏性迁移。
- 补全 OpenAPI 描述，包括主要路径、请求/响应模型、Bearer 安全方案、错误码和公开/需登录标识；浏览器可打开 Swagger UI 并携带 Bearer Token 试调主要接口。
- 新增仓库级 `apitest/` 黑盒接口测试套件：一个接口一个脚本，按 URL/HTTP 方法组织；`run_all.py` 一键运行并生成 Git 忽略的 HTML 报告；除状态码外核对响应内容与 PostgreSQL 持久化结果。
- 为接口测试提供隔离的本地 Docker Compose 测试配置和可控 OpenAI-compatible 生成/嵌入替身，至少覆盖登录、检索、提示词/技能、创建会话并发送一条消息。
- 更新运维与范围说明，移除“多轮会话、技能、多智能体”作为非目标的旧限制，并说明新数据、配置、测试与流式连接边界。

## Capabilities

### New Capabilities

- `agents/agent-management`: 定义班级作用域内智能体、提示词、技能、创建者权限以及草稿/发布生命周期。
- `conversations/grounded-agent-chat`: 定义学生会话、受控多轮历史、每轮班级检索、SSE 流式回答、引用与失败行为。
- `operations/openapi-documentation`: 定义完整 OpenAPI/Swagger 可发现性、Bearer 试调和接口/错误契约。
- `testing/api-contract-tests`: 定义按 URL 组织的独立接口测试、数据库一致性断言、隔离环境和 HTML 报告。

### Modified Capabilities

- `materials/knowledge-retrieval`: 将“只允许单轮、不得使用历史”的绝对限制调整为：旧知识库问答接口继续保持单轮；新的智能体会话可使用受限历史，但每一轮仍必须重新执行本班检索、证据授权、引用校验和跨班不可区分处理。

## Impact

- **后端与数据**：FastAPI 路由/模式、认证依赖、生成与检索编排、SQLAlchemy 模型、Alembic 迁移及 PostgreSQL 会新增智能体、技能、绑定关系、会话、消息和引用相关数据。
- **模型调用**：生成提示将组合教师配置、受限会话历史、技能规则和本轮授权证据；端点、密钥、班级边界及日志最小化规则保持服务端控制。
- **前端**：React 增加教师智能体管理页面、学生会话列表/聊天页面、SSE 增量展示、引用来源和可访问状态反馈；原材料与单次问答入口保持可用。
- **API 兼容性**：新增接口和 OpenAPI 契约；现有登录、材料、检索及 `POST /api/knowledge/query` 不删除、不改为流式。
- **运行与测试**：Docker Compose、网关流式代理配置、测试替身、`apitest/`、Git 忽略规则和运维文档需要扩展；HTML 报告及测试运行数据不得提交 Git。
- **规约关系**：项目主规格目录当前为空，相关已实现规约仍位于已完成但未归档的变更 `add-class-scoped-knowledge-retrieval` 与 `add-class-isolated-material-library` 中；本变更沿用其既有 capability 路径与服务端班级隔离约束，不创建近似重复能力。
