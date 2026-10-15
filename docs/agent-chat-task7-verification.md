# Agent Chat：Task 7 验证记录

变更：`add-class-agent-chat-and-api-testing`（`spec-driven`）。

本轮完成并勾选 **7.1–7.7，共 7 项**，总进度 **39/60**。Task 8–10 未实施、未勾选，变更尚不可归档。任务来源见 [tasks.md](../openspec/changes/add-class-agent-chat-and-api-testing/tasks.md)。

## 实现与验收

| 任务 | 实现与证据 |
| --- | --- |
| 7.1 | `frontend/src/agent-api.ts` 提供类型化的智能体/技能 CRUD、发布、学生会话、创建者审计与授权下载。Bearer fetch SSE 解析器校验分片 UTF-8、LF/CRLF、心跳、连续序号、稳定标识、事件阶段、唯一终态、当前引用集合、配置一致性、答案长度和 SHA-256；拒绝多余字段和非授权下载地址。32 项 API/解析器测试覆盖 401、中断、序号缺口、错误摘要、重复引用、额外敏感字段等。不使用 EventSource，不自动重试发送。 |
| 7.2 | `/agents/manage` 只允许教师进入，集合由服务端限制为创建者本人；支持多个智能体、私有提示词、技能维护与绑定、发布/取消发布、就绪错误和确认停用。可显式移除已停用技能绑定以修复配置。表单有标签、长度限制、空白检查与键盘操作测试。 |
| 7.3 | `/conversations` 使用服务端安全目录，不获取学生无权查看的私有技能或提示词；支持创建、列表、重访和确认软删除，隐藏已删除记录，披露教师对身份、问题、回答与引用的保留审计权限。覆盖空目录、不可用智能体及删除后的焦点恢复。 |
| 7.4 | `/conversations/:conversationId` 限制一次发送一条消息，提供命名 live region、增量文本、配置更新提示、只读不可用状态和明确的中断状态。中断后须显式刷新服务器记录，不自动重发；刷新发现仍在处理时继续禁止发送。答案/历史均为 React 纯文本，只有匹配当前消息有效来源的引用会生成可聚焦链接；下载重新携带 Bearer 并由服务端授权。 |
| 7.5 | `/agents/:agentId/audit` 与详情页显示活动及学生已删除记录、学生身份、消息状态、配置版本和来源。支持删除状态筛选与逐页加载全部保留历史；审计页面没有发送表单。学生路由守卫与非创建者 404 均有组件覆盖，真实跨班教师拒绝亦经网关验证。 |
| 7.6 | 原材料、上传和单轮知识库问答保留；资料页提供按角色区分的新导航。原 5 项浏览器测试与新 3 项浏览器测试一起通过。 |
| 7.7 | 前端 lint、typecheck、全部 Vitest、生产构建和全部 Playwright 检查通过；未修改依赖版本或降低质量门槛。 |

主要实现：[API](../frontend/src/agent-api.ts)、[教师管理](../frontend/src/agents.tsx)、[会话与审计](../frontend/src/conversations.tsx)。主要测试：[API/SSE](../frontend/src/agent-api.test.ts)、[组件](../frontend/src/agent-experience.test.tsx)、[浏览器](../frontend/e2e/agent-chat.spec.ts)。

## 最终检查

- `cd frontend && npm run quality`：退出 0，包括 ESLint `--max-warnings 0`、TypeScript、**59/59 Vitest**（5 个文件）及 Vite 生产构建。
- `cd frontend && npm run test:e2e`：退出 0，**8/8 Playwright**，无跳过。实际使用独立 Nginx 网关与生产 Web 镜像，而非 Vite 开发服务器。
- 新 e2e 文件另用 `tsc --noEmit --strict --skipLibCheck --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2023,DOM --types node e2e/agent-chat.spec.ts` 校验：退出 0。
- 主动 LSP 检查 10 个相关 TS/TSX 文件：最终未报告 warning/error，9 个确认 clean，1 个 push-only 服务器复查结果 inconclusive，**不将其宣称为已确认 clean**；TypeScript 全项目校验作为独立证据。两条扩展名提示按 Vite bundler 解析约定标为误报，未添加忽略注释、修改 lint 规则或放宽编译选项。
- API/Web Docker 构建、Nginx `-t`、独立 Compose 配置解析：退出 0。
- `openspec validate add-class-agent-chat-and-api-testing --strict` 及 `openspec validate --all --strict`：退出 0，后者 4/4 通过。裸 `openspec validate --strict` 在当前非交互 CLI 中要求指定目标，已改用上述显式目标命令验证。
- `git diff --check`：通过。

## 浏览器证据与边界

真实服务流程覆盖：教师创建技能、创建并发布智能体 → 同班学生创建会话 → SSE 无证据拒答 → 教师更新配置 → 下一轮配置更新提示 → 重载保留消息 → 学生确认删除后不能读取 → 创建者仍能读取完整记录 → 另一班教师读取为 404。该流程使用真实 PostgreSQL 持久化及重载读取，但不冒充 Task 8/9 的独立数据库一致性断言。

有引用的回答、恶意标记纯文本渲染、键盘引用跳转、授权下载和中断恢复另外使用浏览器 HTTP/SSE 合成夹具验证。移动端视口为 390×844，断言无横向溢出、焦点顺序、live region 与零 pageerror。没有调用真实模型，也不把夹具当作模型语义或真实检索准确率的证明。

## 隔离与清理

使用现有 Compose 配置加临时 override，项目名为 `campusclaw-task7`；独立 PostgreSQL/资料/Qdrant 卷，独立 API/Web 镜像名，只有网关绑定 `127.0.0.1:18087`，API 和数据库均无主机端口。测试端点/密钥为空，凭据均为合成值，临时环境文件未入库。

验收后已删除本轮 7 个容器、3 个卷、2 个网络及临时环境/override 文件。原有 5 个容器保持运行，未部署或重启既有业务栈。本轮只修改 Task 7 前端、测试、该任务复选框及本报告；既有后端与 Nginx 未提交改动保持不动，未重跑完整后端测试，未 commit/push。

原有 `materials/knowledge-retrieval` 主规格尚未同步的归档顺序 INFO 仍存在，属于待执行的 Task 10.7；本轮不提前同步或归档。
