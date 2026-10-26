## 1. 数据与运行时配置

- [x] 1.1 在现有 Settings 增加 MCP 运行时密钥与批准 URL→环境变量名映射，校验规范化origin、无userinfo/query/fragment、禁止重定向/环境代理；用配置单测验证允许mcp-demo、拒绝任意目标且错误不含秘密。
- [x] 1.2 新增服务器、连接代次、发现工具、最小调用审计模型和仓储，建立(class_id,name)、(assistant_message_id,tool_ref)等唯一约束；用PostgreSQL测试验证同班重名拒绝、不同班同名及班级过滤。
- [x] 1.3 为技能修订增加稳定工具绑定、assistant增加安全tool_calls快照，编写Alembic迁移并回填旧技能knowledge_search和旧消息空列表；在隔离旧数据上验证upgrade、约束与历史可读，测试可选downgrade不在演示库执行。

## 2. 同仓 MCP 演示服务

- [x] 2.1 建立mcp-server独立Python项目、锁文件、Dockerfile与.dockerignore，运行时读取MCP_AUTH_TOKEN并在缺失/空值时拒绝启动；构建测试验证镜像层无密钥且公开health不依赖模型。
- [x] 2.2 实现Bearer保护的POST /mcp、initialize、notifications/initialized与tools/list，固定协议2024-11-05与JSON响应子集；协议测试覆盖401、202通知、握手、请求ID、JSON-RPC四类错误及413/415。
- [x] 2.3 实现formula_hint的有限主题提示与question输入schema；单测验证tools/list发现、支持主题文本结果、未知主题isError、输入界限且不执行指令。
- [x] 2.4 实现unit_convert的有限单位集合与确定性问题解析，不使用eval；单测验证100cm→1m、单位维度、非有限数/表达式/不支持问题及文本结果界限。
- [x] 2.5 在主docker-compose.yml构建mcp-demo并与API共享内部网络，运行时注入同一MCP_AUTH_TOKEN且不设API硬健康依赖；Compose测试验证无8090主机映射、无数据库/材料卷及MCP故障不阻止API启动。
- [x] 2.6 更新.env.example空占位与运维配置说明，不读取/改写真实.env；静态检查验证令牌不作为build arg、Docker ENV常量、前端变量或跟踪文件提交。

## 3. 主机登记、连接与发现

- [x] 3.1 增加班级共享MCP登记/列表路由及安全响应schema，名称与URL创建后不可变；API测试覆盖教师201、重名409、无令牌401、学生403、跨班404和客户端class字段400。
- [x] 3.2 新增有界httpx MCP客户端，使用服务端令牌完成initialize→initialized→tools/list并校验ID/版本/返回结构；测试验证令牌不复用用户JWT、错误安全脱敏、3秒RPC/8秒连接deadline与64KiB响应限制。
- [x] 3.3 实现connect代次CAS与原子发现缓存、断开清空及幂等接口，校验工具名称/schema/数量；并发测试验证断开或新connect不能被迟到握手覆盖，失败后无可用缓存。
- [x] 3.4 实现tools安全元数据列表与兼容question schema标识，不兼容工具不可绑定；测试验证formula_hint/unit_convert可见、断开空列表、非法发现失败及unsupported工具状态。
- [x] 3.5 为每种连接错误提供固定safe code与可操作提示；回归测试验证远端401、超时、错误RPC和异常发现返回503但旧knowledge/query和无MCP对话仍可用。

## 4. 技能工具绑定与修订

- [x] 4.1 扩展技能请求/响应与修订服务的tools字段，创建省略默认knowledge_search、更新省略保留旧值、显式空值仅清MCP；单测覆盖旧客户端兼容、重复/格式/8项上限400。
- [x] 4.2 在同一事务校验同班稳定server_id、连接代次、缓存成员和参数schema兼容性；服务测试验证不可访问404、断开/未发现/不兼容409与整笔修订回滚。
- [x] 4.3 将工具绑定纳入不可变修订与原有agent传播/重新发布流程，校验合并MCP引用最多8项；测试验证修改后草稿、重新发布后使用新修订、旧历史保持原配置且仅创建者可改技能。

## 5. 监督调用、审计与对话数据边界

- [x] 5.1 将对话工具阶段放入execute_turn监督协程，从已接受修订生成去重有序计划，仅取当前问题有界前缀构造question参数；测试验证每引用每turn最多派发一次、无模型/历史/资料诱发调用。
- [x] 5.2 实现派发前短事务授权、唯一pending记录与结果接收时代次校验，拒绝项也留最小审计；并发测试覆盖跨班/断开无HTTP调用、已派发迟到结果denied、接收已提交的ok不被事后断开追溯篡改。
- [x] 5.3 实现3秒单次/10秒阶段预算、无tools/call重试、ok/denied/error安全映射和独立审计提交；测试覆盖isError、空/非文本/超大响应、HTTP/协议错误与预算耗尽，并验证普通回答可继续。
- [x] 5.4 将断连、turn超时及进程中断的pending调用收敛为唯一终态，不重放远端调用，迟到生成worker不得写审计；任务测试验证无重复派发、无迟到覆盖、审计不可写则不调用远端。
- [x] 5.5 扩展ChatService输入为独立untrusted_tool_results用户数据段，维持工具结果非事实证据及资料引用策略并增加8000字符辅助预算；捕获模型输入测试确认系统消息不含工具正文/凭证、无资料仍先记工具再精确拒答、无递归工具。
- [x] 5.6 扩展完成/错误SSE终态meta.tool_calls、assistant快照和历史安全schema；流/持久化测试核对与审计一致、无工具为空列表、生成失败仍留工具状态、事件顺序/序号/摘要/引用未变。
- [x] 5.7 增加教师本班分页审计端点，仅返回ref、状态、安全原因、用户与时间/turn标识；测试验证分页、同班教师共享、学生403、跨班过滤404且无问题/参数/原始结果/凭证。
- [x] 5.8 回归旧单轮查询、无工具技能、多轮solution_guidance、当前引用重新授权及并发409；自动化测试证明MCP未改变既有主路径和最终答案限制。

## 6. 前端与 Swagger

- [x] 6.1 添加教师“本班MCP”管理导航与列表/登记/连接/断开/发现工具状态，不提供token输入；组件测试验证真实API契约调用、错误提示与学生无入口、可键盘操作。
- [x] 6.2 扩展现有技能编辑器工具选择与类型，保留不可用旧绑定并提示保存409；组件测试验证formula_hint@campus-tools可选、旧客户端省略语义与不静默丢绑定。
- [x] 6.3 添加本班最小工具审计视图及学生会话tool_calls状态，更新TypeScript/SSE解析和历史渲染；前端测试覆盖ok/denied/error、completed/error终态和不执行远端文本。
- [x] 6.4 补齐MCP各路由、技能tools及终态meta的FastAPI OpenAPI注解和安全错误schema，继续使用同源Swagger；文档测试核对路径、Bearer、400/401/403/404/409/503与无真实密钥示例。

## 7. 隔离 API 验收与报告

- [x] 7.1 在独立docker-compose.apitest.yml加入实际mcp-server构建与仅测试用运行时凭证，保留内部网络、隔离卷和模型替身；stack测试确认不复用演示资源、不调用外部模型。
- [x] 7.2 按URL/方法组织MCP登记/列表/connect/tools/disconnect/audits操作脚本及共享HTTP前置逻辑；run_all.py --list验证新操作被发现，逐操作断言schema/值、401/403/404与只读SQL持久化一致性。
- [x] 7.3 扩展技能与消息正式用例：真实连接演示MCP→保存formula_hint引用→创建/发布agent→有本班资料的学生问答→audit ok；核对stream、assistant、审计三方一致，不以主机mock替代远端。
- [x] 7.4 扩展同会话断开负例、失败连接与无资料场景，使用明确观察断言验证断开后无远端再派发且denied、保存409、无资料拒答；受控异常HTTP测试补齐注入与迟到结果，不把这些替身测试冒充真实闭环。
- [x] 7.5 更新apitest SSE解析与固定安全报告标签，为只读reader仅授权必要安全列；支持层测试验证无写权限、无密码/原始秘密读取和报告脱敏。
- [x] 7.6 运行完整独立run_all.py生成HTML报告并保留失败退出码；确认旧操作与新增操作共同通过、报告路径被Git忽略，记录实际执行结果而非只报测试设计。
- [x] 7.7 扩展真实浏览器Swagger验收：登录/Authorize、登记/connect/tools/技能保存；验证同源请求、用户JWT与MCP令牌分离、无浏览器错误，截图前清理敏感面板并存忽略目录。

## 8. 最终验证与交付证据

- [x] 8.1 按六份spec全部Scenario核对覆盖矩阵，执行MCP协议测试、后端/前端回归、格式/类型/LSP检查与openspec validate --strict；记录命令、通过/失败/未执行项，不擅自跳过旧用例。
- [x] 8.2 在获准的演示部署实际验证health、Bearer tools/list/call、主机连接发现、绑定问答和断开拒绝；检查运行时令牌一致性仅输出布尔值，避免docker compose config或环境dump泄密。
- [x] 8.3 检查Git跟踪文件、镜像历史/层、前端产物与日志无运行时令牌，确认HTML报告不入Git；交付安全扫描结果与不含秘密的证据索引。
- [x] 8.4 更新README移除MCP非目标旧描述，补充operations、apitest与MCP子集/工具参数/回滚说明，新增Scenario验收记录；核对文档链接存在、限定真实验证范围且不声称已核验课件全文。
