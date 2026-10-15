# Task 10 最终验收

变更：`add-class-agent-chat-and-api-testing`，schema：`spec-driven`。
本轮完成 10.1–10.7，整体 **60/60**。未归档、commit 或 push。

## 本轮变更

- `.env.example` 补齐聊天字段、历史、心跳、总期限、限流与生成超时；`docker-compose.yml` 将这些参数及既有生成/查询预算传入 API。
- README 与 operations 更新教师独立智能体/技能、多轮引导、每轮重新检索、缓冲验证后 SSE、同源 Swagger、软删与创建者审计、备份回滚和隔离测试命令。未移除旧查询、Bearer、班级隔离或模型外发批准要求。
- 新增 `test_chat_legacy_regression.py`：私有配置/会话建立前后旧查询响应及 provider payload 相等；跨班、普通缺证、泛知识、秘密请求及问题中旧答案均拒答；生成失败不妨碍身份、材料上传/下载和安全 health。
- 增强真实 PostgreSQL 迁移测试：从检索旧 head 升至最终 head，保留班级、用户哈希/角色、材料摘要/路径/归属及活跃检索 chunk 的 ID/版本/正文/材料关联，验证新增表集合及最终 schema。
- 增强不可信教师 prompt/技能与历史的优先级测试；更新过时的学生私有 agent 403 断言为规约既定 404（skill 维护仍 403，agent 创建仍 403）。只修 import 排序/格式，没有放宽规则。
- 将共享 fixture 插件注册移到 conftest，标准 pytest 不再需要 CLI `-p`。提前 `-p` 会在覆盖率启动前导入业务代码，首轮 60% 属于漏计 import；最终标准命令完整测量，无排除/降低阈值。
- `.gitignore` 补充根 `node_modules/`、`.vitest/`，保留已有本地目录而不提交依赖或缓存；将 `materials/` 收窄为 `/materials/`，修复主规格及当前材料 delta 被误忽略的问题。
- Task10.7 同步已完成（61/61）的检索变更到 `openspec/specs/materials/knowledge-retrieval/spec.md`：原 Purpose、14 requirements、56 scenarios 均保留；未归档。当前 delta 恢复旧 Scenario 标题，避免同步后被识别为删除原场景，行为不变。

## 最终执行结果

所有下列正式验收命令退出 0；首轮失败和修正不冒充通过。

| 检查 | 实际结果 |
|---|---|
| API `ruff check .`、`ruff format --check .` | 通过，96 files formatted |
| API `mypy` | 89 source files，通过 |
| API `python -m pytest --junitxml=…`（独立 PostgreSQL） | **249 passed，0 skipped，1 warning；coverage 87.62% ≥ 80%** |
| 前端 `npm run quality`：lint/typecheck/test/build | 全通过，**59 tests / 5 files**，生产构建通过 |
| 前端 `npm run test:e2e -- --trace=off --reporter=list` | Chromium **8/8**，包括原登录/上传/下载/班级边界和新会话/审计/键盘流程 |
| `unittest` 四个 apitest 无服务自测模块 | **23 passed**，包含故意失败/异常/空套件返回非零的自测 |
| apitest Ruff/format、`python -m apitest.check_types` | 37 files；严格 mypy 24 batches 全过 |
| 独立 Compose 空卷 build/up、support stack checks | 通过，support **4 passed** |
| Compose runner 完整套件 | **23/23**；`apitest/reports/task10-full.html` |
| malformed/failure 服务端模型，各运行同一消息操作 | 各 **1/1**，`task10-invalid-output.html` / `task10-provider-failure.html` |
| 实际 Swagger 登录 → Authorize → me Try it out | 同一 principal，恰好一个 Bearer，page/console error 0、external requests 0 |
| docs 回归与相对链接检查 | **4 passed** |
| 开发/生产/独立测试 Compose 配置解析（placeholder 值） | 全通过；API 聊天默认值及生成预算存在 |
| `tests/test_compose_config.py`、`tests/test_compose_ports.py` | 配置及运行栈端口边界通过 |
| 新进程 `uvx pyright --project pyrightconfig.json` | 0 error/warning/information |
| 主动 LSP 八个本轮 Python 文件 | 8 clean，0 diagnostics，无 unsupported/inconclusive |
| `openspec validate --specs --strict`、`--all --strict` | 主 spec 通过；全量 **5 passed**，无 archive-order INFO |
| `git diff --check`、报告/缓存 ignore、最终状态核查 | 通过，无新秘密/运行数据/生成报告待提交 |

保留并披露：后端一条既有 Starlette TestClient/anyio 弃用 warning；浏览器 runner 的 NO_COLOR/FORCE_COLOR warning；OpenSpec 主 spec 有 requirement 长度 >500 的 INFO（不是 archive-order，未为了消除提示擅改旧 requirement）。不声称零告警。

### 浏览器、模型与网络证据边界

Docker Desktop 仍未实际绑定 internal-only 测试网关的宿主端口。浏览器使用经项目标签校验的短生命周期 loopback TCP → docker exec/nc → 同一个 gateway 桥接；没有新增外网网络或 API/DB 端口。内部 runner 不用桥接。本轮不声称直接宿主 18088 发布成功。

8 个浏览器测试中，真实教师管理/学生拒答/配置更新/软删/创建者审计及原登录/上传下载经过真实网关与 PostgreSQL；移动键盘引用、连接中断和旧查询引用导航使用显式 HTTP/SSE fixtures。它们验证浏览器行为，不伪装为真实生成/数据库断言；成功引用、当前修订、两类失败及 SQL 一致性另由真实隔离黑盒栈和后端测试验证。

所有生成均为内部确定性替身或测试内受控 provider；没有真实外部模型质量/自然语言绝对安全证明，也没有真实用户资料外发。

## 五份 delta spec 的逐 Scenario 矩阵

下面 **97 个 Scenario 全部执行通过，无未测行**。证据缩写指本轮已执行的测试，不是静态检查推测。后端 pytest 的最终 JUnit 为 249 个 testcase、0 failure/error/skip。参数化测试覆盖全部参数。

### 证据索引

除 B/H/UI 外，路径均相对 `api/tests/`。

| ID | 本轮执行的证据 |
|---|---|
| A1 | `test_agent_conversation_postgres.py::test_agent_and_skill_crud_match_database_and_revision_identity` |
| A2 | 同文件 `test_invalid_requests_are_safe_400_without_partial_rows`、`test_configured_bounds_and_retirement_do_not_allow_partial_updates` |
| A3 | 同文件 `test_maintenance_hides_noncreator_and_other_class` |
| A4 | 同文件 `test_students_cannot_maintain_or_mutate_resources`；`test_agent_api.py::test_student_private_agent_identifiers_are_hidden_without_mutation` |
| A5 | `test_agent_conversation_postgres.py::test_publication_idempotence_readiness_and_invalid_updates_are_atomic`；`test_agent_api.py::test_publish_requires_guidance_and_controls_student_catalog` |
| A6 | `test_agent_services.py` 两个 lifecycle/invalid binding 测试；B 的 agent DELETE/PATCH/skill DELETE 操作含退休与 SQL 断言 |
| C1 | `test_agent_conversation_postgres.py::test_conversation_lifecycle_audit_deleted_filters_and_history_paging`、`test_full_audit_history_is_retrievable_in_bounded_pages` |
| C2 | 同文件 `test_conversation_identifier_isolation_and_current_class`、`test_conversations_order_by_timestamp_then_id_and_creation_readiness` |
| C3 | 同文件 `test_message_validation_precedes_persistence`；`test_agent_chat_contracts.py` fabricated-state 参数化测试 |
| G1 | `test_chat_generation.py::test_prompt_keeps_private_text_in_typed_untrusted_data_not_platform_policy`（恶意教师 prompt、技能及历史分区、固定平台策略） |
| G2 | 同文件 `test_history_is_recent_bounded_excludes_current_and_other_conversations` |
| G3 | 同文件 `test_unsafe_or_non_guidance_output_is_never_released`、`test_output_bounds_and_current_citation_equality` |
| S1 | `test_chat_streaming.py::test_success_is_unicode_safe_ordered_and_exactly_persisted`；`test_chat_postgres.py::test_postgres_guidance_stream_equals_messages_and_source_snapshots` |
| S2 | `test_chat_streaming.py::test_no_evidence_refusal_never_calls_generation` |
| S3 | 同文件 `test_post_start_failure_is_redacted_and_terminal`、`test_timeout_persists_failed_and_late_worker_cannot_overwrite` |
| S4 | 同文件 `test_invalid_output_repairs_once_without_echo_and_never_releases_partial_text` |
| S5 | 同文件 `test_prompt_and_skill_changes_apply_next_turn_and_preserve_prior_audit` |
| S6 | 同文件 `test_pre_stream_rejections_rate_and_size_create_no_extra_rows` |
| S7 | 同文件 `test_heartbeat_concurrent_conflict_and_other_conversation_independence`；PostgreSQL simultaneous/one-409 测试 |
| S8 | 同文件 `test_disconnect_does_not_cancel_accepted_work` |
| S9 | 同文件 `test_source_revoked_during_generation_releases_no_model_text`；G3 的 stale S9/空当前 evidence 拒绝 |
| S10 | 同文件 `test_other_class_only_evidence_is_indistinguishable_from_no_evidence` |
| S11 | 同文件 `test_contextual_followup_retrieves_fresh_evidence_and_only_own_history` |
| L1 | `test_chat_legacy_regression.py::test_legacy_query_is_identical_before_and_after_private_chat_configuration` |
| O1 | `test_openapi_documentation.py::test_all_operations_security_input_output_errors_and_references` |
| O2 | 同文件 `test_sse_contract_declares_all_serializer_models_and_temporal_rules` |
| O3 | 同文件 `test_documentation_never_serializes_runtime_secrets_or_private_database_content`、`test_public_swagger_is_same_origin_without_inline_script_or_cdn` |
| O4 | 同文件 `test_actual_auth_and_domain_errors_match_documented_safe_shape` |
| B | 独立 Compose runner 23/23 及支持层 4/4；各操作含 schema/授权/SQL，错误模型补跑各 1/1；HTML 仅固定 allowlist 诊断，无运行内容 |
| H1 | `apitest.tests.test_harness`：稳定发现、重复/非法注册、失败继续、异常/secret 标签/stdout 丢弃、空套件、HTML 转义/离线等 11 测试 |
| H2 | `apitest.tests.test_cases`：23 操作发现及 schema 负例；`test_clients` 六测试；`test_stub` 四测试 |
| UI | `frontend/e2e/agent-chat.spec.ts` 三测试与 `demo.spec.ts` 五测试；前端 59 个单测 |
| SW | `node apitest/browser_swagger.mjs` 真实 Chromium Try it out；刷新清授权后截图 |
| ENV | 空卷独立栈、无默认 egress 路由、reader 拒写/拒 hash、原五个容器 ID/名称前后相等、ignored 报告检查 |

### agents/agent-management — 23/23

| Scenario | 已通过证据 |
|---|---|
| Teacher creates an agent | A1, B |
| Student attempts to create an agent | A4, B |
| Client supplies ownership scope | A2, B |
| Teacher saves a valid prompt | A1, B |
| Prompt requests a policy override | G1, G3 |
| Configuration exceeds a bound | A2 |
| Teacher creates a solution-guidance skill | A1, B |
| Another teacher modifies a skill | A3, B |
| Student reads teacher maintenance APIs | A4, B |
| Creator binds a compatible skill | A1, B |
| Creator binds an inaccessible skill | A5, A6, B |
| Bound skill is retired | A6, B |
| Teacher publishes a valid agent | A5, B, UI |
| Required guidance skill is absent | A5, B |
| Student asks for only the final answer | G3, S1, B |
| Student lists available agents | A5, B |
| Teacher updates a published prompt or skill | S5, B, UI |
| Agent is unpublished | A5, S6, B |
| Creator manages an agent | A1, B, UI |
| Another teacher manages an agent | A3, B |
| Other-class user guesses an agent identifier | A3, A4, B |
| Creator retires an unused draft | A6, B |
| Creator retires an agent with history | A6, B |

### conversations/grounded-agent-chat — 34/34

| Scenario | 已通过证据 |
|---|---|
| Student creates a conversation | C1, B, UI |
| Student lists conversations | C1, C2, B |
| Student accesses another conversation | C2, B |
| Student soft-deletes a conversation | C1, B, UI |
| Agent creator opens an active conversation | C1, B |
| Agent creator opens a student-deleted conversation | C1, B, UI |
| Another teacher requests the conversation | C2, B, UI |
| Student sends a message | S1, B |
| Relevant evidence exists only in another class | S10, B |
| Student class changed after conversation creation | C2, S6 |
| Student asks a contextual follow-up | G2, S11 |
| Old history exceeds a limit | G2 |
| Client submits fabricated history | C3, B |
| Prior answer cited a source | G3, S9, S11 |
| Prompt changes between turns | S5, B, UI |
| Agent becomes unpublished or invalid | S6, A6, B |
| Student requests a direct final answer | G3, S1, B |
| Agent prompt conflicts with platform policy | G1, G3 |
| Answer streams successfully | S1, B |
| Evidence is insufficient | S2, S10, B, UI |
| Configuration changed | S5, B, UI |
| Stream event contains sensitive internals | S1, S3, S4, H2, B |
| Request fails before streaming | C3, S6, B |
| Generation provider fails after start | S3, B（503 分支） |
| Model output fails validation | S4, B（malformed 分支） |
| Turn completes | S1, B |
| Turn fails after acceptance | S3, S4, B |
| Client disconnects | S8 |
| Second message arrives during generation | S7, B |
| Different conversation sends a message | S7 |
| Student receives streamed content | UI |
| Stream is interrupted | UI |
| Student uses keyboard or assistive technology | UI（键盘、焦点、live region、移动视口） |
| Student deletes a conversation | UI（保留审计披露、确认、列表隐藏） |

### materials/knowledge-retrieval — 7/7

| Scenario | 已通过证据 |
|---|---|
| Sufficient evidence exists | L1, S1, B |
| Question asks for general model knowledge | L1, S2 |
| Question asks for reasoning traces or hidden instructions | L1, G1, G3 |
| Previous answer text is supplied as part of a new request | L1（问题内旧答案不成为证据） |
| Agent chat uses persisted history | S11, G2 |
| Client supplies fabricated chat history | C3, B |
| Prior citation is absent from current evidence | G3, S9, S11 |

### operations/openapi-documentation — 12/12

| Scenario | 已通过证据 |
|---|---|
| Client loads the OpenAPI document | O1, B |
| Major interface is inspected | O1, B |
| Streaming operation is inspected | O2, B |
| User authorizes Swagger | SW |
| Protected operation has no token | O4, B |
| Public operation is inspected | O1, B |
| Agent publication conflict is inspected | O1, A5, B |
| Cross-class resource is requested | O4, A3, B |
| Request validation fails | O4, A2, B |
| User opens Swagger through the gateway | SW, B |
| User tries a main workflow | SW（登录、授权、身份） |
| Documentation is downloaded | O3, B |

### testing/api-contract-tests — 21/21

| Scenario | 已通过证据 |
|---|---|
| Login case is located | H2, B |
| One path supports multiple methods | H1, H2 |
| Shared setup is required | H2, B（独立操作注册，共享支持层） |
| All cases pass | B（23/23、报告与 exit 0） |
| One case fails | H1（失败/异常继续收集、非零退出） |
| Report output is considered for commit | ENV |
| Test environment starts | ENV, B |
| Existing development stack is running | ENV（测试项目独立，原五容器不变） |
| External model configuration is absent | ENV, H2, B |
| Login succeeds | B（登录 POST + DB identity） |
| Login fails | B（unknown/wrong 密码 401 相等） |
| Streamed message completes | B（SSE/SQL 精确对照） |
| Cross-class identifier is used | B, A3, C2 |
| Agent and skill are persisted | B（CRUD/绑定/修订/发布 SQL） |
| Conversation and one message are persisted | B（owner/class/消息/修订/引用 SQL） |
| Unauthorized mutation is attempted | B（DB snapshot 不变） |
| Required coverage is discovered | H2, B |
| Knowledge retrieval is checked | B（两班引用、他班专有事实与普通拒答相同） |
| Guidance behavior is checked | B, G3 |
| Authentication assertion fails | H1（token/password/labels/stdout 脱敏） |
| Generation assertion fails | H1, B（无效输出仅安全诊断） |

## 状态、清理与限制

- 报告、安全词汇、Git ignore、spec Scenario 数量及最终测试符号已交叉核查；97/97 无漏项。最终工作区 137 个待提交路径均为本功能源码/规格/测试/文档；三个 vendored Swagger CSP PNG 是经哈希测试的源码资产，不是运行截图。
- 独立测试栈与临时 PostgreSQL、测试卷/网络及桥接均清理；现有五个运行容器 ID/名称不变。未请求开发 API 或读写开发数据库。
- 工作区原已有整个功能的未提交实现；保留它们。新增根缓存忽略规则不删除本地依赖或测试缓存。
- 当前主规格只同步前置检索能力；本变更仍 active，后续归档再合并它的五份 delta。未提前把聊天 delta 写成主规格。
- HTML、截图及浏览器布尔回执仍为 ignored 本地产物；不提交 token、凭据、运行数据、模型输出或生成报告。
