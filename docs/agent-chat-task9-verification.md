# Task 9 黑盒 API 验收记录

变更：`add-class-agent-chat-and-api-testing`。本轮完成 **9.1–9.8**；整体 **53/60**。
Task 10 的七项保持未勾选；没有归档、commit 或 push。

## 实现范围

- `apitest/cases/`：23 个独立 URL/方法脚本，前置数据各自通过网关建立，不依赖前一个脚本。
- `apitest/scenarios.py`：独立公开 OpenAPI 响应验证、HTTP 前置数据、只读 SQL 和 SSE/数据库比对；不导入业务实现。
- `run_all.py`：支持 `openapi.json` 等真实 URL 段及精确 `--operation` 选择；未匹配仍失败。
- 成功断言标签去重，避免重复状态码检查挤掉报告中的数据库/安全检查类别。
- 测试替身增加服务端模型选择的固定 2 秒延迟，默认 `fixture-delayed`，使并发冲突可重复；保留无效输出与 503 模型。
- `check_types.py` 对 URL 目录里的同名 GET/POST 脚本逐个执行严格 mypy，不忽略操作代码。
- `browser_swagger.mjs` 为可选真实 Chromium 补验，不替代 Compose runner。
- 运行步骤与失败模式命令见 `apitest/README.md`。

## 用户确认的契约修复

首轮黑盒验收发现：学生访问私有智能体标识接口返回 403，而规约要求隐藏存在性的 404。
经用户明确选择“按规约修复后端”，本轮最小修改：

- 智能体私有 GET/PATCH/DELETE、publish/unpublish 以受支持的身份进入服务端资源授权。
- `AgentService.read` 对非教师统一抛出 missing-resource，其他创建者/班级继续使用查询范围隐藏。
- 集合创建仍要求教师，学生 POST `/api/agents` 继续返回 403；学生 GET 集合仍是安全已发布目录。
- 新增后端回归：真实/不存在 ID 的五种私有操作均 404 且正文一致，数据库状态/修订不变。
- 未修改规约或放宽授权；未通过放宽测试来接受原有偏差。

其余首轮失败属于测试错误：SQL 表名、时间字符串 `Z`/`+00:00` 比较、把绑定幂等误写为整次配置更新不产生修订。已分别改为真实表名、时刻值比较、当前修订恰好一个绑定并验证旧修订绑定不变。配置重复更新仍允许创建不可变修订，未削弱绑定唯一性断言。

## Task 验收矩阵

| Task | 操作脚本 | 已执行的主要断言 |
|---|---|---|
| 9.1 | `/api/auth/login` POST | 教师/学生登录，Bearer 元数据、到期时间、身份与 DB 一致；未知账户/错误密码通用 401 相等；用户行不变 |
| 9.2 | `/api/knowledge/query` POST | 两班各自引用、材料/chunk/当前索引版本范围；他班专有内容与普通无证据响应完全相等；输入/未认证；DB 不变 |
| 9.3 | `/api/skills` GET/POST、`/{skill_id}` GET/PATCH/DELETE | CRUD、字段边界、学生禁止、同班非创建者/他班/不存在 404；作用域/不可变修订/绑定传播；退休导致 agent 失效且无新消息 |
| 9.4 | `/api/agents` GET/POST、`/{agent_id}` GET/PATCH/DELETE、publish/unpublish POST | 多草稿、prompt 修订、绑定唯一/无权限引用回滚、发布就绪、学生安全目录、退休历史与发布指针、学生私有标识 404 |
| 9.5 | `/api/conversations` GET/POST、`/{conversation_id}` GET/DELETE、两个 creator audit GET | 服务端 owner/class、隐藏他人会话、分页、软删保留与披露、创建者保留完整审计、非创建者/他班 404、删除后阻止消息 |
| 9.6 | `/api/conversations/{conversation_id}/messages` POST | SSE 类型/顺序/连续序号/共同 ID/摘要、Unicode 字节分块解析、指导而非最终答案、当前授权引用、prompt 与 skill 更新通知、旧审计不变、精确拒答、并发 409、预流错误、两种流内失败 |
| 9.7 | `/api/openapi.json` GET、`/api/docs` GET | 主路径/方法/状态/请求与响应模型、唯一 operation IDs、公开/保护标识、单 Bearer 方案、SSE 全部事件 schema、同源资产/无私有内容；实际浏览器 Try it out 补验 |
| 9.8 | 完整 Compose runner | 空卷启动与重复运行均 23/23；HTML 含各操作响应/DB 检查；严格安全标签/无内容泄露；报告 ignored 且不被 Git 跟踪 |

成功 SSE 将 user/assistant ID、ordinal、作用域、消息内容、终态、完成时间、检索模式、应用修订、configuration_updated 和 citation snapshot 与 PostgreSQL 精确比较；引用额外 JOIN 当前 active 索引和 ready 材料验证，不仅比对 API 自身。两种失败均只有 started/error，持久化一条用户消息和一条 failed assistant，正文为空、错误码安全、无引用。

## 实际执行结果

| 检查 | 结果 |
|---|---|
| 空测试卷迁移、fixtures、索引、API、gateway 健康启动 | 通过 |
| 最终完整 HTML `apitest/reports/task9-full.html` | **23/23**，31.351s，exit 0 |
| 不清数据的重复执行 `task9-repeat.html` | **23/23**，31.371s，exit 0 |
| 服务端 `fixture-malformed`，消息脚本 `task9-invalid-output.html` | **1/1**，`generation_invalid`，exit 0 |
| 服务端 `fixture-failure`，消息脚本 `task9-provider-failure.html` | **1/1**，`answer_generation_unavailable`，exit 0 |
| 无服务支持层/发现/schema 自测 | **23 passed** |
| 真实栈支持验收（只读权限/无默认路由/索引/网关/SSE） | **4 passed** |
| 相关后端回归 | **32 passed**，未运行全后端覆盖率 |
| Ruff + 格式检查 | apitest 与三个后端变更文件全部通过 |
| 严格 mypy | apitest 24 批（支持层 + 23 操作）全部通过；三个后端变更文件通过 |
| 新进程 Pyright | 独立 apitest 配置、根配置均 0 error/warning/information |
| 主动 LSP | 34 个源码文件，无 LSP 错误；两个辅助规则误报已按具体身份处置，无 inline suppression；另一个数值转换提示已改写消除 |
| Node 语法检查 | 通过 |
| OpenSpec `validate --all --strict` | 4 passed；既有主 spec 未同步的 archive-order INFO 仍在，留待 10.7 |
| `git diff --check` | 通过 |

后端聚焦测试需显式 `-p tests.test_conversation_api` 注册共享 fixture：首次不显式注册时出现 fixture-not-found，修正测试调用后为 32 passed。没有为此改动不相关测试组织，也不把该结果当作 Task 10 全回归/覆盖率。

## 实际浏览器与网络边界

Chromium 实际点击 Swagger 登录的 Try it out，取得合成用户 token 后通过 Authorize 再执行身份接口：HTTP 200、身份相同、恰好一个 Bearer 头、页面/控制台错误 0、外部请求 0。
截图前刷新清除授权状态和请求/响应面板，未保存 token、HAR、trace 或浏览器持久化状态。
证据：`apitest/artifacts/task9-browser.json`、`apitest/artifacts/task9-swagger.png`（均 ignored）。

本机 Docker Desktop 对 `internal: true` 网络配置保留了 HostConfig 端口声明，但实际宿主端口绑定为空，直接访问 18088 被拒绝。浏览器补验使用脚本内短生命周期 loopback → docker exec/nc → 同一个 gateway 的桥接；因此**不声称直接宿主端口发布成功**。桥接未接入新网络、未给 API/数据库映射端口、未增加外网路由。Compose runner 始终从内部网络直接访问 gateway，无桥接。API 重建后等待健康并重启 Nginx，避免旧容器 IP 缓存。

全部模型请求使用内部确定性替身；没有真实模型或外部内容请求。runner 仍只获 test reader 凭据，权限测试拒绝写库、schema 创建与 password_hash 读取。

## 报告安全、清理及剩余范围

- 四份最终报告均逐行核对固定 allowlist 诊断词汇；23 操作报告包含响应类别与适用 DB 断言类别。
- 检查无 JWT、密码、数据库连接串、私有指令、资料内容或原始 provider 输出；失败自测继续验证 secret-bearing exception/label/stdout 不进入报告。
- `git check-ignore` 确认最终报告 ignored；`git ls-files apitest/reports apitest/artifacts` 为空。
- 独立测试 8 个服务容器、3 个卷、1 个内部网络已清理；临时 runner 均 `--rm`，浏览器及本地 TCP 桥接已关闭。
- 初始 5 个运行容器 ID/名称完全不变；未请求开发 API 或读写开发数据库。
- 保留此前未提交文件、node_modules 和 `.vitest/`；未 commit/push。
- **Task 10 未执行完成、未勾选**：范围/运维总文档、完整后端覆盖率与全前端回归、五份 spec 的最终全 Scenario 矩阵、主 spec 同步/归档顺序仍待后续工作。
