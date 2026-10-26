# AI 应用平台五项验证问题答复

## 一、先说明平台功能与要求的对应关系

| 要求 | 当前情况 | 可采用的准确表述 |
|---|---|---|
| 内置多个 AI 应用 | 已在当前部署新增并发布 3 个演示应用，学生目录已回读确认；是教师配置的多个独立智能体 | 当前部署提供物理概念导学、力学解题陪练、单位换算检查三个教学应用；不是出厂种子自动内置，也不是多智能体协作 |
| 提示词模板 | 可保存、编辑应用级 `system_prompt`，为本次演示写入了三个可复用模板 | 支持应用级提示词配置；没有独立模板市场、变量替换或模板版本管理界面，不等于不存在配置修订 |
| 知识库检索 | 本班材料自动纳入检索；支持 PDF、UTF-8 文本和 Markdown，keyword/vector/hybrid | 每轮按本班授权检索，再组装有界证据；没有逐应用手动选择知识库的绑定器 |
| 内置 Skill 及上传 | 内置 `solution_guidance` 类型和强制引导策略，支持教师在线创建/编辑/绑定技能；未实现技能文件导入 | 已有指令型解题引导 Skill；**“支持上传技能文件”未满足**，不能用上传资料或粘贴指令替代 |
| 外部工具及 MCP | 内置 `knowledge_search`，支持批准服务器上的有限 MCP 只读工具 | 支持 `formula_hint`、`unit_convert` 的服务端调用；不是任意外部工具平台或完整通用 MCP 客户端 |

因此，**当前不能把原始五项要求全部写成已完整达标**。本次只补充了现有能力范围内的演示配置与资料，没有新增业务能力或修改规约。

### 本次实际完成与未完成的验证

已完成：正常 API 登录后新增并回读三组应用/技能/提示词，发布成功，学生目录可见；四份合成材料经过四个索引任务后均为 `searchable`；独立 MCP 服务器连接并发现两种可绑定工具。操作只增补本次演示内容，没有修改原有应用。

未完成：本次没有发送聊天请求、生成请求，没有模型原始请求/响应抓包，没有测量模型输出质量和费用。资料索引可能调用已配置 embedding 服务，不能称“零模型相关费用”。运行时模型端点已配置不等于已验证其可用性或真实服务类型。

## 二、问题 1：每次对话传给 LLM 的参数、返回内容是什么？模板会一起发送吗？

### 1. 必须区分三层通信

```text
浏览器 ──当前问题──> 平台 API
                    │
                    ├──服务端加载配置/历史，执行工具及本班检索
                    │
                    └──messages 等参数──> 模型接口
                                         │
                    <──原始模型 JSON──────┘
                    │
浏览器 <──校验、授权、持久化后的 SSE── 平台 API
```

浏览器的聊天请求是：

```http
POST /api/conversations/<conversation_id>/messages
Content-Type: application/json
```

```json
{"content":"将 100 cm 转换为 m"}
```

浏览器另外携带登录 Bearer token，它只用于平台身份认证。客户端不提交教师 prompt、技能指令、历史、班级 ID、上游模型密钥或上游模型参数。服务端拒绝伪造历史等未知字段。

### 2. 平台 → 生成模型的请求参数

代码确认：`GenerationClient.complete()` 向服务端配置的生成 endpoint 发送 `POST`，地址按 `/chat/completions` 补全（已以该后缀结尾时不重复追加）。请求正文只有以下字段；`response_format` 取决于配置：

| 字段 | 含义 | 本次运行容器配置回读值 |
|---|---|---|
| `model` | 模型标识 | `course-chat` |
| `temperature` | 采样温度 | `0.0` |
| `max_tokens` | 输出 token 上限，不是输入上下文上限 | `256` |
| `messages` | 两条消息：system 与 user | 下面展开 |
| `response_format` | 开启结构化模式时发送 | `{"type":"json_object"}` |

这些是本次**运行配置快照**，不是某个已发生请求的抓包值；后续配置变化应重新取证。源码默认模型名为 `grounded-answer`，不能把默认值写成本次运行模型名。超时通过 HTTP 客户端参数设置，不是请求 JSON 中的字段。

`Content-Type` 为 JSON。若设置生成密钥，后端使用独立的上游 Bearer 密钥，不转发学生 JWT。地址和密钥不返回浏览器，本文不列出运行时秘密。

下面是**结构示意，不是可直接重放的真实请求**；中文占位文字代表需要从实际代码/取证结果展开的内容：

```json
{
  "model": "course-chat",
  "temperature": 0.0,
  "max_tokens": 256,
  "messages": [
    {"role": "system", "content": "平台固定聊天策略 + Mandatory solution guidance + 强制解题引导策略"},
    {"role": "user", "content": "序列化后的配置、历史、问题、工具辅助结果、本轮授权证据 JSON 数组"}
  ],
  "response_format": {"type": "json_object"}
}
```

具体两条 message 的构成是：

- `system.content`：`CHAT_PLATFORM_POLICY + "\nMandatory solution guidance:\n" + SOLUTION_GUIDANCE_POLICY`。固定策略要求本班证据、引用、引导、保密和工具隔离，不使用教师 prompt 直接替换 system。
- `user.content`：下列数组经 `json.dumps(..., ensure_ascii=False)` 序列化后的**字符串**，不是额外的顶层 JSON 字段，也不是五条独立消息：

```json
[
  {
    "field": "untrusted_teacher_configuration",
    "prompt": "本轮接受时选定的已发布修订中的 system_prompt 全文",
    "skills": ["该修订绑定的技能 instructions 全文，可能有多条"]
  },
  {
    "field": "untrusted_persisted_history",
    "messages": [{"role": "user", "content": "服务端加载的有界历史文本"}]
  },
  {"field": "current_question", "value": "当前问题，首尾空白已去除"},
  {
    "field": "untrusted_tool_results",
    "results": [{"ref": "unit_convert@screenshot-demo-tools", "text": "成功工具的辅助正文", "truncated": false}]
  },
  {
    "field": "current_authorized_evidence",
    "sources": [{"source_id": "S1", "text": "本轮检索、授权、预算筛选后的 chunk 原文"}]
  }
]
```

新会话的历史列表为空；没有成功工具时 results 为空。历史中的 user/assistant 是嵌套数据，不是上游 `messages` 的独立 role 消息。当前运行历史预算为最多 20 条、24000 字符的确定性最近完成消息后缀，并非整个账户聊天记录。

### 3. 提示词模板是否发送？

**会，但有条件。**有授权证据并进入生成阶段时，服务端读取本轮接受时锁定的有效已发布配置，把保存的教师提示词全文放入 user 数据中的 `untrusted_teacher_configuration.prompt`。它的字段名虽然叫 `system_prompt`，实际不会作为最高优先级 system 消息传入。

本次准备的模板全文见[操作指南第 9 节](ai-platform-browser-guide.md#9-已写入平台的提示词与技能全文)。不是只传模板 ID，也不是由浏览器每轮重新上传模板。更新配置后须满足发布条件，下一轮才能应用新版本；生成中途不换成刚编辑的草稿。

**重要例外：**无授权证据时直接跳过生成。因此不能说“每一次聊天都一定向 LLM 发送提示词”。无效输入、权限失败、应用未发布也可能在模型调用前结束。

### 4. 模型返回什么，浏览器又收到什么？

上游适配器从 OpenAI-compatible 响应外壳中读取：

```text
choices[0].message.content
```

它必须是有界字符串。以下只是**合法结构样例，不是本次真实返回**：

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "{\"status\":\"insufficient_evidence\",\"guidance\":[],\"answer\":\"\",\"citation_ids\":[]}"
    }
  }]
}
```

聊天模型的 content 内部必须是严格 JSON，字段恰为：

| 字段 | 约束 |
|---|---|
| `status` | `answered` 或 `insufficient_evidence` |
| `guidance` | 最多 8 段 `{kind,text}`，kind 为 hint/step/check/question；有回答时至少有 check 或 question |
| `answer` | 等于各引导段文本以换行拼接的结果 |
| `citation_ids` | 与本轮行内引用对应，只能使用本轮授权来源 |

模型若宣称证据不足，必须返回空 guidance、空 answer、空 citation_ids。平台会把它规范为用户看到的 **`根据本班资料无法回答该问题`**。没有任何可用证据时，平台也能不调用模型直接返回同一句话。

校验不通过时最多进行一次结构修复；修复请求在原 user 文本后追加固定纠正指令，不把无效原始输出回灌模型。仍不通过则安全失败。所以一轮对话可能没有生成请求、发生一次生成请求，或有一次额外修复请求；浏览器的一次 POST 不代表上游恰好一次调用。

浏览器接收 `message.started` → 零或多个 `answer.delta` → 零或多个 `citation` → `message.completed` 或 `message.error`。先完整获取并校验模型结果，再交付文本增量，**不是把上游 token 流直接透传**。终态有 `meta.tool_calls`；历史保存通过校验的答案、引用、版本、状态等，不保存 provider 原始响应。

上游可能有 usage、finish_reason、响应 ID 等额外字段；当前适配器未把它们返回前端，不能从 UI 反推其实际值或费用。SSE 的完成也不等于通用语义正确性的形式化证明。

## 三、问题 2：绑定知识库后，每次是否把全部知识库内容传给 LLM？

**不是按全量知识库发送，而是检索后发送有界证据片段。**当前“知识库范围”由登录班级自动确定，不提供应用级手动知识库绑定界面。

处理顺序：

1. 根据服务端认证结果确定班级，不能由问题或模型扩大范围。
2. 每轮重新检索本班 ready、有效版本的材料。聊天固定 hybrid；依赖不可用时可降级 keyword-only。
3. 检索查询以当前问题为主，在长度限制内可补入最多三条历史用户消息帮助理解指代；不是把整个历史当查询或事实证据。
4. 向量检索只返回候选标识，必须从 PostgreSQL 回读 chunk 正文并重新授权。
5. 按排名和预算选证据，赋本轮临时来源编号 `S1`、`S2` 等。
6. 仅把选中的 `{source_id,text}` 放入 `current_authorized_evidence.sources`。

本次运行 `QUERY_MAX_RESULT_LIMIT=12`，`GENERATION_EVIDENCE_CHAR_BUDGET=6000`。选取完整 chunk，累计超过预算时停止，并非把所有文档拼成 6000 字摘要。6000 是证据正文字符预算，不是整个 HTTP 请求或 token 预算。

**需要避免的过度结论：**

- 小知识库、候选很少时，本次选中的片段可能恰好覆盖全部资料；“采用 RAG”并不保证每次都严格小于全库。
- 返回给用户的是模型实际引用的来源，可能小于发送给模型的完整证据集。仅看来源卡不能证明上游没有带其他 chunk。
- 第二轮仍会重新检索，不是第一轮把知识库“永久灌给模型”。历史可能包含旧引导文本，但不得作为本轮事实支持。
- 无证据时跳过生成；有检索片段但模型判定不足时，也应拒答。仅凭同一句拒答无法区分这两条路径。

另外，**资料入库的 embedding** 和**问答的 generation** 要分开看：入库时会分块发送支持索引的资料文本给批准的 embedding 服务；问答向量检索可能发送当前查询作 embedding。这不等于每轮向聊天生成接口发送全量知识库。

浏览器操作对应 S04、S07；严格验证“本轮究竟发送哪些片段”，需要 U01/U03 的完整上游 payload，不能只用页面截图代替。

## 四、问题 3：绑定 Skill 后，每次 LLM 请求是否包含技能全部内容？

**当前实现会把本轮绑定技能修订的 `instructions` 全文发送，但并非整个 Skill 对象或技能文件包。前提仍是本轮进入生成阶段。**

| Skill 内容 | 是否作为该内容发送给生成模型 |
|---|---|
| 各绑定技能的 `instructions` 全文 | 是，放入 `untrusted_teacher_configuration.skills` 数组 |
| 平台强制解题引导策略 | 是，放入 system 消息 |
| 技能名、技能 ID、修订 ID、创建者等完整元数据 | 不作为 Skill 对象整包发送 |
| `tools` 中的 MCP 连接、凭据、发现 schema | 不整包发送；由服务端决定实际工具调用 |
| 成功工具的引用名和有界结果 | 是，另放 `untrusted_tool_results`，不是技能指令 |
| `SKILL.md`、脚本、资源目录、ZIP 附件 | 没有此类导入/执行机制 |

这里没有“先只展示技能简介，模型选中后再懒加载全文”的渐进式机制，也没有模型语义匹配后只激活一个 Skill。当前已发布修订里的全部有效绑定技能均参与本轮。

技能指令在保存阶段有长度校验，发送阶段取已保存修订的全文；“全文”指这一版合法保存的字符串，不包括未保存草稿或历史版本。即使工具执行失败，有证据并进入生成时，相应已绑定技能指令仍会出现在配置段，失败工具正文不会加入辅助段。

没有证据时没有生成请求，因此也没有“把全文发给 LLM”这一步。Skill 管理页截图只证明配置存在；全文实际传输需要 U03 逐字对照。

## 五、问题 4：执行具体 Skill 的逻辑是什么？

当前 Skill 是**指令与工具绑定配置**，不是运行任意代码的插件。执行由服务端编排，而非让模型阅读一个技能文件后自主执行脚本。

```text
学生发消息
  ↓
认证、学生/班级/会话归属、应用发布状态、并发与输入校验
  ↓
选定有效已发布应用修订，建立本轮消息并记录版本
  ↓
把全部有效绑定 Skill 当作本轮匹配项
  ↓
合并、去重、排序 MCP 引用，检查连接/发现状态与权限
  ↓
每个合规工具最多尝试一次；记录 ok / denied / error
  ↓
服务端加载有界历史，重新检索本班资料并选择证据
  ├─ 无证据 → 跳过生成、精确拒答，仍保留工具状态
  └─ 有证据 → 拼接平台策略、完整教师/技能指令、历史、问题、工具辅助、证据
                    ↓
                调用模型
                    ↓
                严格校验；最多一次修复
                    ↓
                重新授权引用，保存终态，交付 SSE
```

以“单位换算检查”为例：技能绑定 `unit_convert@screenshot-demo-tools`。学生发送固定单位转换问题时，服务端调用该工具取得辅助结果，然后仍要检索本班“长度单位换算检查卡”；模型应根据课程证据给换算方向或列式提示，并让学生自查，不应直接照抄工具的最终数值。

代码能保证编排、权限、格式、引用集合、限额和失败处理等边界；不能声称正则和结构化校验能证明任意自然语言永远没有直接给答案或无据推断。真实引导质量需另做模型回答验证。

本次三个应用不是三个可执行 Skill 引擎，而是同一机制中的不同配置。浏览器 S10–S13 能观察配置和执行状态，但不能看到进程内每一步完整内容。

## 六、问题 5：集成 MCP 后，每次传给 LLM 的参数是什么？

### 1. 发给生成模型的顶层参数不改成工具调用接口

仍是第二部分的 `model`、`temperature`、`max_tokens`、`messages`、可选 `response_format`。

**当前不发送 OpenAI 原生 function-calling 的 `tools`、`tool_choice`、`functions`、`function_call`，也不添加 `role: tool` 消息。**模型不选择服务器、工具或参数，不会生成原生工具调用再由服务端回填。

变化在 user 字符串中的独立段，例如下面的**合成示意**：

```json
{
  "field": "untrusted_tool_results",
  "results": [
    {
      "ref": "unit_convert@screenshot-demo-tools",
      "text": "这里是该次成功工具返回的文本，非真实抓包内容",
      "truncated": false
    }
  ]
}
```

每个工具有效结果最多 4000 字符，合并辅助正文最多 8000 字符；只纳入已授权且最终 `ok` 的结果。拒绝、超时、错误结果不放入这个列表。工具文字不能变成 system 指令、课程证据或新调用授权，不能自己创建 `S1` 引用。

### 2. 平台 → MCP 是另一条独立请求

代码确认的实际协议结构如下，ID 为每次生成值；这是协议示例，非已捕获流量：

```http
POST http://mcp-demo:8090/mcp
Accept: application/json
Content-Type: application/json
Authorization: Bearer <仅服务端注入，不能截图的 MCP 专用凭据>
```

```json
{
  "jsonrpc": "2.0",
  "id": "<本次请求ID>",
  "method": "tools/call",
  "params": {
    "name": "unit_convert",
    "arguments": {"question": "将 100 cm 转换为 m"}
  }
}
```

MCP 收到的参数只有**当前问题前 2000 字符**，不包括历史、课程材料、教师模板、技能指令、学生 JWT 或身份字段。长问题的剩余部分不会交给工具；生成阶段的当前问题仍按聊天输入约束处理。

连接发现阶段另有 `initialize`、`notifications/initialized`、`tools/list`；不是每轮都把整个工具列表传给生成模型。支持协议为 `2024-11-05` 的有限 POST JSON-RPC 子集，不支持任意 stdio、GET SSE、OAuth、批处理或通用 MCP SDK 兼容保证。

每轮多个技能引用同一 MCP 工具只调一次；去重后的全部有效绑定按服务端计划尝试，不按问题语义让 LLM 选择。最多 8 个 MCP 引用，单次工具调用预算 3 秒、工具阶段预算 10 秒，不进行工具自动重试或递归调用。

### 3. 返回给浏览器的只是安全状态

例如：

```json
{
  "meta": {
    "tool_calls": [
      {"tool_ref":"unit_convert@screenshot-demo-tools","status":"ok","code":"ok"}
    ]
  }
}
```

这只是终态事件中的字段片段，不是模型原始响应。历史 assistant 消息的 `tool_calls` 保存相同状态项；教师审计页还能查看发起用户、时间、会话与回合标识，但不提供参数、原始工具结果或密钥。

`ok` 只证明授权工具执行成功，不代表模型有充分证据或最终回答正确。无证据也会先尝试工具，然后跳过生成并拒答；MCP 故障本身也不必阻断有充分资料的普通引导。

## 七、单轮知识库问答与多轮应用聊天不要混为一谈

| 项目 | `/api/knowledge/query` | `/api/conversations/{id}/messages` |
|---|---|---|
| 浏览器请求 | `question`、`result_limit:10`、`mode` | `content` |
| 教师模板、绑定 Skill | 不使用 | 使用当前接受的发布修订 |
| 历史 | 不自动携带 | 服务端有界加载 |
| MCP | 不调用 | 尝试全部有效绑定 |
| 模型策略 | `SYSTEM_PROMPT` 加 prompt version | `CHAT_PLATFORM_POLICY` 加强制解题引导 |
| 模型 content 字段 | status、answer、citation_ids | 另要求 guidance |
| 对浏览器返回 | 非流式 JSON | 校验后 SSE |

本次应以**学生智能体会话**为五项验证主路径，不能在“知识库问答”页面提问后宣称已经验证应用模板、Skill 和 MCP 的联合执行。

## 八、代码和规约依据

以下链接均为本仓库文件；函数名便于后续代码移动后定位。本文为源码核对与有限部署状态验证，不冒称对所有 Scenario 做了新一轮回归。

| 结论 | 主要依据 |
|---|---|
| 上游生成、embedding 参数及返回解析 | [providers.py](../api/src/campusclaw/application/providers.py)：`GenerationClient.complete`、`EmbeddingClient.embed` |
| 教师模板、全部 Skill 指令、历史、工具与证据的消息组装；无证据短路；修复 | [chat.py](../api/src/campusclaw/application/chat.py)：`ChatService.prompt/generate` |
| 证据筛选、完整 chunk 预算、引用校验、单轮策略 | [generation.py](../api/src/campusclaw/application/generation.py)：`select_evidence`、`GroundedAnswerService` |
| 监督执行顺序、终态落库、精确拒答转换 | [chat_tasks.py](../api/src/campusclaw/application/chat_tasks.py)：`execute_turn`、`_finish` |
| 技能类型、默认工具、维护与强制引导策略 | [skills.py](../api/src/campusclaw/application/skills.py)：`SkillService`、`SOLUTION_GUIDANCE_POLICY` |
| 工具匹配、去重、权限、参数截取与安全审计 | [mcp_execution.py](../api/src/campusclaw/application/mcp_execution.py)：`McpToolStage` |
| MCP 协议、连接发现、真实请求结构与结果边界 | [mcp_client.py](../api/src/campusclaw/application/mcp_client.py)：`rpc/discover/call` |
| 浏览器只发 content，SSE 解析 | [agent-api.ts](../frontend/src/agent-api.ts)：`send` |
| 提示词和技能界面，无文件导入入口 | [agents.tsx](../frontend/src/agents.tsx) |
| 材料上传与单轮问答 | [materials.tsx](../frontend/src/materials.tsx) |
| 默认值与 Compose 运行注入 | [config.py](../api/src/campusclaw/config.py)、[docker-compose.yml](../docker-compose.yml) |
| 班级知识检索主规约 | [knowledge-retrieval/spec.md](../openspec/specs/materials/knowledge-retrieval/spec.md) |
| 应用、技能和多轮聊天规约 | [agent-management/spec.md](../openspec/changes/add-class-agent-chat-and-api-testing/specs/agents/agent-management/spec.md)、[grounded-agent-chat/spec.md](../openspec/changes/add-class-agent-chat-and-api-testing/specs/conversations/grounded-agent-chat/spec.md) |
| MCP 编排与辅助数据边界规约 | [MCP grounded-agent-chat/spec.md](../openspec/changes/add-class-mcp-tool-integration/specs/conversations/grounded-agent-chat/spec.md) |
| 部署与已存在验收记录 | [operations.md](operations.md)、[mcp-acceptance.md](mcp-acceptance.md) |

## 九、可直接用于汇报的简短答复

1. **对话参数与模板：**浏览器只发当前问题；后端在有证据的生成请求中发送模型参数、平台策略，以及包含教师模板全文、技能指令、有界历史、当前问题、工具辅助结果和本轮证据的 user 数据。浏览器收到的是校验后的 SSE，不是原始模型响应。
2. **知识库：**先在本班范围检索，再按条数和字符预算发送选中 chunk，不是每次固定全量上传。小库可能恰好全被选中；引用卡不能代替完整请求取证。
3. **Skill 内容：**进入生成时发送绑定技能的 instructions 全文，但不发送整个技能对象、代码包、凭据或连接配置；无证据时跳过生成。
4. **Skill 执行：**由服务端把全部有效绑定视为匹配，执行去重且授权的工具，再检索、组装、生成、校验和保存，不是模型自主规划或执行上传脚本。
5. **MCP 参数：**生成请求仍用两条 messages，不使用原生 function calling；成功工具文本放 user 的独立不可信辅助段。后端另向 MCP 发 tools/call，仅传当前问题前 2000 字符。

**验收边界：**三组演示配置和资料已经准备并回读确认；生成效果与原始上游流量仍需按指南实际取证。技能文件上传当前未实现，不能写成已通过。

![S01-app-catalog](/Users/wafoe/Desktop/S01-app-catalog.png)

![S02-prompt-configuration](/Users/wafoe/Desktop/S02-prompt-configuration.png)

![S03-skill-configuration](/Users/wafoe/Desktop/S03-skill-configuration.png)

![S04-searchable-materials](/Users/wafoe/Desktop/S04-searchable-materials.png)

![S05-browser-chat-payload](/Users/wafoe/Desktop/S05-browser-chat-payload.png)

![S06-browser-chat-terminal](/Users/wafoe/Desktop/S06-browser-chat-terminal.png)

![S07-grounded-guidance](/Users/wafoe/Desktop/S07-grounded-guidance.png)

![S08-persisted-history](/Users/wafoe/Desktop/S08-persisted-history.png)

![S09-mcp-discovery](/Users/wafoe/Desktop/S09-mcp-discovery.png)

![S10-skill-mcp-binding](/Users/wafoe/Desktop/S10-skill-mcp-binding.png)

![S11-mcp-terminal](/Users/wafoe/Desktop/S11-mcp-terminal.png)

![S12-mcp-chat-ui](/Users/wafoe/Desktop/S12-mcp-chat-ui.png)

![S13-mcp-audit](/Users/wafoe/Desktop/S13-mcp-audit.png)

![S14-mechanics-app](/Users/wafoe/Desktop/S14-mechanics-app.png)
