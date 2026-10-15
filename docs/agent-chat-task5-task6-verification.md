# Agent Chat：Task 5 / Task 6 验证记录

变更：`add-class-agent-chat-and-api-testing`（`spec-driven`）。

本轮完成 **5.1–5.8、6.1–6.5，共 13 项**。任务总进度 **32/60**；Task 7–10 未实现或勾选，当前变更尚不应归档。详见 [tasks.md](../openspec/changes/add-class-agent-chat-and-api-testing/tasks.md)。

## 实现与验收对应

| 任务 | 实现及验证 |
| --- | --- |
| 5.1 | 复用证据选取、来源序列化与最终重新授权；向量客户端延迟初始化，避免无嵌入服务时无意义的连接。旧单轮知识接口、grounding、provider boundary 和班级隔离回归通过。 |
| 5.2 | SQL 限量加载同会话、同学生、同班级、同 agent 的已完成历史；排除刚受理的当前问题。按消息数及字符预算取确定性后缀；检索查询使用当前问题与至多三条近期用户上下文，并受 `QUERY_MAX_LENGTH` 限制。 |
| 5.3 | 固定平台政策与强制解题引导放在 system 消息；教师配置、技能、历史、当前问题及当前证据作为分区 JSON 数据，不能改变服务端班级、端点或工具权限。 |
| 5.4 | 严格校验 guidance 类型、渲染答案一致性、当前引用集合、长度、标记和 Unicode；拒绝额外字段及明确的直接最终答案格式。最多修复一次，修复请求不回送原始无效输出。拒答使用固定文本且无引用。 |
| 5.5 | 受理事务选定当时有效的已发布不可变版本；本轮生成及持久化使用该版本，不被中途草稿替换。后续 prompt/skill 更新使用新版本，持久化并发送 `configuration_updated`。未发布配置在开流前返回 409。 |
| 5.6 | 五类事件共享严格类型、标识符及连续序号。验证 Unicode 增量重组、事件顺序、唯一终态、引用快照与答案摘要一致。 |
| 5.7 | 应用持有与断连独立的有界任务；心跳为注释。全部输出校验、最终来源/身份复核及终态提交之后才发送文本。真实 ASGI 断连、超时、迟到结果、并发冲突、来源撤销、provider 异常与无效输出场景均验证终态。 |
| 5.8 | PostgreSQL 用户锁保护跨会话限流；默认每学生每分钟 30 条。默认消息上限 8,000 字符，JSON 字节上限为 `4 × 消息字符上限 + 1,024`；默认任务超时 90 秒。日志只记录固定安全结果码。 |
| 6.1 | 共享 HTTP Bearer JWT 安全依赖；保留原有大小写/空白解析、令牌及身份复核、精确 401 响应与 Cookie 不参与认证的行为。 |
| 6.2 | `/api/docs`、`/api/openapi.json` 经 Nginx 同源访问；Swagger UI 5.17.14 固定版本资源随 API 分发。CSS 数据图片解码为同源文件并由独立样式覆盖，未放宽 CSP。真实 Chromium 授权与试调通过，API 无主机端口映射。 |
| 6.3 | 补全 operation ID、tag、summary、输入、输出、预期错误与媒体类型。手动解析的知识请求和 multipart 上传也有输入契约。框架校验错误改为不回显输入的安全结构；旧接口保留 422 状态，新资源继续使用 400，原知识接口自身的 400 契约不变。 |
| 6.4 | OpenAPI 声明 SSE 媒体类型及所有事件模型，并区分开流前 JSON 错误、开流后 `message.error`、心跳、断连与不支持自动重放。 |
| 6.5 | 文档/静态资源扫描验证不包含运行时密钥、令牌、数据库地址、教师 prompt、skill、学生消息、资料正文或平台政策正文。 |

主要新增测试：[生成与历史](../api/tests/test_chat_generation.py)、[SSE 生命周期](../api/tests/test_chat_streaming.py)、[PostgreSQL](../api/tests/test_chat_postgres.py)、[OpenAPI/Swagger](../api/tests/test_openapi_documentation.py)。

## 最终验证

- 全后端 PostgreSQL 测试：**246 passed，0 failed，0 errors，0 skipped**；覆盖率 **86.58%**，超过既有 80% 门槛。
- Ruff、格式检查、mypy（88 个文件）、fresh Pyright：全部通过。
- 主动 LSP 检查本轮涉及的 25 个 Python 文件：零诊断。
- `openspec validate --all --strict`：4 个变更全部通过；`git diff --check` 通过。
- 新 API 镜像构建、Nginx 配置检查、Compose 配置解析：通过。
- 最终镜像经独立网关的 Chromium 验证：**30 个操作、试调 HTTP 200、相同 principal、恰好一个 Bearer 头、零浏览器/CSP 错误、零外部资源请求**。
- PostgreSQL 迁移验证覆盖新增 `configuration_updated` 列，迁移头为 `20261015_0006`。

## 隔离、兼容性与边界

测试只使用独立的 `campusclaw-task56-*` 临时容器及合成数据，不调用真实生成/嵌入模型。修正测试夹具的 `create_all(checkfirst=False)`，防止新 schema 因 `search_path` 发现 public 同名表而误用它；迁移测试也先建立独立的空版本表，避免读取 public 版本号。最终全量测试前后，隔离网关 public 各表的行内容摘要完全一致。

三个临时容器及临时网络已删除；既有五个容器保留，未部署或重启现有开发栈。既有未提交文件以及 `.vitest/`、`node_modules/` 保留；本轮未 commit/push。

保留一条既有 Starlette `anyio.abc.BlockingPortal` 弃用警告，以及 knowledge-retrieval 主规格尚未同步导致的归档顺序 INFO；后者属于未执行的 Task 10.7。

解题引导的结构校验、平台政策及对抗验收样例已落实，但不声称能形式化证明任意自然语言的最终答案语义，这与设计中的既有非目标一致。Task 7–10 的产品前端、独立黑盒套件及最终部署验收仍待后续实施。
