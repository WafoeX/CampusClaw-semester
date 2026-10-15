# CampusClaw 运维指南

本指南介绍了本学期支持的部署方式。默认前提是已经安装 Docker 和 Docker Compose，并且所有命令均在代码仓库的根目录下执行。

## 运行时拓扑

Compose 服务栈包含：

* `web`：Nginx 网关以及构建完成的 React 应用。这是唯一配置了主机 `ports` 端口映射的服务，通常访问地址为 `http://localhost:8080`。
* `api`：运行在内部 8000 端口上的 FastAPI 应用。`web` 服务可以访问该服务，但该端口不会发布到主机。
* `migrate`：使用 API 镜像运行的一次性容器，用于执行 `alembic upgrade head`。
* `seed`：使用 API 镜像运行的一次性容器，用于执行由环境变量控制的演示数据初始化。
* `db`：运行在内部数据网络中的 PostgreSQL 16。其端口不会发布到主机。
* `qdrant`：内部、可重建的向量索引，仅保存浮点向量和 PostgreSQL chunk ID/class/material/version 标识；无主机端口。
* `indexer`：内部 durable worker，读取材料卷并写 PostgreSQL/Qdrant；无主机端口。

网关会将同源的 `/api/*` 和 `/health` 请求代理至 `api:8000`。因此，API 和数据库均属于 Compose 内部服务，而不是独立暴露在主机上的端点。`postgres-data` 用于存储关系型数据，`materials-data` 用于存储上传的文件，`qdrant-data` 用于可选的向量快照。PostgreSQL 是 chunk 正文、来源、生命周期和授权的唯一权威存储。

可以通过以下命令检查这一服务边界：

```sh
docker compose config --format json

python tests/test_compose_ports.py
```

端口检查结果应仅显示 Web 网关。

## 准备服务器配置

将配置模板复制为一个被版本控制忽略的文件，并填写所有必填但当前为空的配置值：

```sh
cp .env.example .env

openssl rand -hex 32                 # JWT_SIGNING_KEY

openssl rand -hex 24                 # POSTGRES_PASSWORD
```

将 `DATABASE_URL` 配置为使用 Compose 数据库服务名，而不是 `localhost`：

```dotenv
DATABASE_URL=postgresql+psycopg://campusclaw:<url-encoded-password>@db/campusclaw

POSTGRES_PASSWORD=<same-password>

JWT_SIGNING_KEY=<at-least-32-random-bytes>
```

如果生成的密码中包含 URL 保留字符，则需要在 `DATABASE_URL` 中对密码进行 URL 编码；而 `POSTGRES_PASSWORD` 中仍应保留原始密码。

`.env` 文件应仅保存在服务器端，绝不能提交到版本库中。不要将数据库 URL、JWT 签名密钥或演示账户密码写入 React 源代码或 `VITE_*` 环境变量中。

## 演示环境启动

演示环境配置默认启用具有幂等性的示例数据初始化。请通过 `.env` 提供全部四个示例账户的密码，然后启动服务栈：

```sh
docker compose --env-file .env up -d --build db migrate seed api web

docker compose --env-file .env ps
```

启动顺序依次为：

1. 数据库通过健康检查；
2. 数据库迁移完成；
3. 示例数据初始化完成；
4. API 通过健康检查；
5. Web 网关启动。

通过已发布的网关检查服务是否准备就绪：

```sh
curl -fsS http://localhost:${WEB_PORT:-8080}/health
```

演示环境中的身份账户是固定的，并分别属于两个相互隔离的班级：

* `teacher.alpha` 和 `student.alpha` 属于 `Alpha Class`；
* `teacher.beta` 和 `student.beta` 属于 `Beta Class`。

这些账户的密码分别来自服务器环境中的对应 `DEMO_*_PASSWORD` 配置值。

密码会通过正常的 Argon2id 流程进行哈希处理，并且 API 永远不会打印或返回密码。

重复运行 `seed` 是安全的：它不会创建重复记录，不会重置密码，不会覆盖用户自行创建的教学资料，也不会修改已经存在且有效的种子数据记录。

如需查看一次性服务的输出，同时避免暴露环境变量值，可以运行：

```sh
docker compose --env-file .env logs --no-color migrate seed

docker compose --env-file .env ps
```

## 生产环境启动

生产环境应使用生产配置覆盖文件。该配置会设置 `APP_ENV=production` 并默认禁用演示数据初始化：

```sh
docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --build db migrate seed api web
```

使用该命令启动时，不会创建任何示例班级、示例账户、示例教学资料数据库记录或示例文件。

在向用户公开生产环境 Web 端点之前，必须在其前方部署 HTTPS，以保护登录凭据和 Authorization Bearer Token 不在传输过程中泄露。

运维人员可以在受控演示场景下主动启用种子数据覆盖配置，但仍然必须提供全部四个账户密码：

```sh
SEED_DEMO_DATA=true docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm seed
```

不要在真实生产租户环境中启用这一选项。

该覆盖配置需要显式启用，从而保证默认行为是安全的，同时使这一行为能够被测试。

## 知识库问答、索引和数据边界

资料库提供 `keyword`、`vector` 和 `hybrid` 三种检索方式，省略方式时使用 hybrid，并用固定 RRF 合并独立排名。旧 `POST /api/knowledge/query` 问答保持单轮、非流式；浏览器只发送问题、结果上限和检索方式，不发送班级 ID、历史答案、模型地址或凭据。生成模型只收到服务端重新授权后的有界证据，回答必须引用本次请求的来源 ID；没有充分证据时固定返回 `根据本班资料无法回答该问题`。

仅 PDF、UTF-8 纯文本和 Markdown 建立索引，PDF 不做 OCR；不支持的资料仍可列表、下载。PostgreSQL 保存原文、页码/行号和状态，Qdrant point ID 与 `knowledge_chunks.id` 相同且 payload 不含正文。提示注入被当作不可信资料，不能改变班级、系统策略、工具或引用规则；答案和摘录按纯文本渲染。

嵌入和生成配置独立：优先使用校内私有 HTTPS 端点；`approved_external` 必须由运维显式配置并使用 HTTPS/服务端密钥。端点、密钥、prompt、问题、证据、答案和 provider body 不进入常规日志、health 或 CLI 输出。模型不可用时 keyword 仍可用，hybrid 可安全降级为 `keyword_only`；显式 vector 不回退到 keyword。生成失败返回可重试的安全错误，不把摘录伪装成答案。

常用受控命令（输出仅包含聚合状态，不包含正文）:

```sh
docker compose --env-file .env run --rm --entrypoint campusclaw api backfill
docker compose --env-file .env run --rm --entrypoint campusclaw api indexer
docker compose --env-file .env run --rm --entrypoint campusclaw api index-status --class-id <class-uuid>
docker compose --env-file .env run --rm --entrypoint campusclaw api vector-rebuild
docker compose --env-file .env run --rm --entrypoint campusclaw api qdrant-snapshot
```

更换嵌入模型、维度或距离时必须新建兼容 collection 并从 PostgreSQL authoritative chunks 完整执行 `vector-rebuild`；Qdrant snapshot 只用于加速恢复，不替代 PostgreSQL/materials 协调备份。恢复后运行 `reconcile-vectors`，验证同 ID、class/material/version payload、active ready chunk hydration，并删除 orphan/incompatible points。生成模型或 prompt 版本变化不需要重建向量，但必须重新通过结构化输出、引用、拒答和提示注入验收。

## 智能体、技能与多轮聊天

教师可维护多个本班、创建者私有的智能体及技能，发布必须有有效 prompt 和活跃的 `solution_guidance` 绑定。学生目录不含私有 prompt 或技能指令。学生只能使用本班有效发布配置；下架、退休或绑定失效立即阻止新会话及旧会话发言。配置更新创建不可变修订，后续消息使用最新有效发布修订并显示配置更新提示，历史保留原应用版本。

聊天仅接收当前问题；客户端不能提交历史、班级、prompt、答案或引用。服务端从同一授权会话加载确定性最近完成消息后缀，历史只帮助理解指代；每轮重新检索本班资料并验证当前引用。平台解题引导、安全、凭据与班级策略高于不可信教师配置、历史和证据。无证据仍精确拒答；不可保证任意自然语言的语义分类是形式化证明。

`.env.example` 的聊天参数会传入 Compose API，默认及允许范围如下（字符按 Unicode 字符计）：

| 参数 | 默认 | 允许范围 |
|---|---:|---|
| `AGENT_NAME_MAX_CHARS` / `SKILL_NAME_MAX_CHARS` | 120 | 1–120 |
| `AGENT_DESCRIPTION_MAX_CHARS` | 1000 | 0–1000 |
| `AGENT_PROMPT_MAX_CHARS` / `SKILL_INSTRUCTIONS_MAX_CHARS` | 12000 | 1–20000 |
| `CONVERSATION_MESSAGE_MAX_CHARS` | 8000 | 1–20000 |
| `CONVERSATION_HISTORY_MAX_MESSAGES` | 20 | 1–100 |
| `CONVERSATION_HISTORY_MAX_CHARS` | 24000 | 1–200000，至少覆盖一个最大消息 |
| `SSE_HEARTBEAT_SECONDS` | 15 | 大于 0、至多 60，小于 task timeout |
| `SSE_TASK_TIMEOUT_SECONDS` | 90 | 大于 0、至多 300 |
| `CONVERSATION_RATE_LIMIT_PER_MINUTE` | 30 | 1–1000，每身份进程内限流 |

单个会话只能有一轮 processing；第二条消息返回预流 JSON 409，不新增消息。生成单次超时默认 30 秒、至多 120 秒，受 `GENERATION_MAX_RETRIES`（默认 1、至多 2）和聊天总任务期限共同约束。结构化验证仅允许一次有界修复；输出 token 默认 256，证据字符预算默认 6000。外部 provider 必须经明确批准；不要为聊天放宽既有模型数据外发规则。

### SSE 与反向代理

`POST /api/conversations/{conversation_id}/messages` 使用 `Authorization: Bearer` 和 fetch，不使用不能携带此头的原生 EventSource。预流错误为 JSON；成功开始后依次是 `message.started`、零或多个 `answer.delta`、零或多个 `citation`、唯一的 `message.completed` 或 `message.error`，有共同 ID 与连续序号。先完整缓冲、验证并再次授权，再持久化并切分文本增量；不是原始 provider token 流。心跳注释不是业务事件。

`frontend/nginx.conf` 对 `/api/` 设置 HTTP/1.1、`proxy_buffering off`、`proxy_request_buffering off` 和 `proxy_read_timeout 330s`，高于最大 300 秒任务预算。外层 TLS 代理也必须禁用响应缓冲/缓存，读取空闲超时大于心跳间隔，并留足总任务预算；不要更改下载附件或 CSP 保护。断线后服务端有界任务仍持久化一次 completed/failed；浏览器标记中断并允许显式刷新，不自动重发/续传，不承诺请求幂等键。

### 审计隐私、保留与回滚

学生删除仅设置 `deleted_at`，立刻隐藏学生列表/读取并阻止发言。创建该智能体的教师仍可在审计页读取问题、回答、来源、状态与学生身份，包括学生已删除会话；同班其他教师与他班用户均收到隐藏存在性的 404。删除确认前必须告知此行为。保留期限、法律依据、访问审批和清除程序由部署方明确告知；本版本没有自动过期或清除任务，不能把软删描述为数据擦除。

备份必须包含会话、消息、引用快照和不可变配置修订；沿用 PostgreSQL 与资料协调备份。不要降级删除新表。回滚旧应用可以保留新增表；聊天异常时停止新写入/隐藏入口，不影响旧登录、材料、单轮查询。日志与报告不记录问题、prompt、历史、答案、凭据或 provider body。

## OpenAPI 与隔离接口验收

同源公开路径 `/api/docs`、`/api/openapi.json` 和 `/api/docs-assets/` 通过现有 Web 网关访问；无需给 API 映射宿主端口。Swagger 先用登录 Try it out 取得 token，再在 Authorize 中只填写 token（不要再加 Bearer 前缀），保护接口以同一 principal 运行且只有一个 Bearer 头。不要共享授权后的截图、curl、HAR 或浏览器存储；使用完清除授权。公开文档不含运行时用户、prompt 或秘密。

隔离测试只使用合成账户/资料和内部确定性模型替身，不能合并开发 Compose 配置，也不能连接已有数据库。从仓库根运行：

```sh
mkdir -p apitest/reports
export APITEST_UID="$(id -u)" APITEST_GID="$(id -g)"
docker compose -f docker-compose.apitest.yml config --quiet
docker compose -f docker-compose.apitest.yml build
docker compose -f docker-compose.apitest.yml up -d --wait
docker compose -f docker-compose.apitest.yml run --rm --no-deps apitest
# 仅销毁独立测试项目，不对开发/生产执行此命令
docker compose -f docker-compose.apitest.yml down --volumes
```

项目名 `campusclaw-apitest`；仅声明 loopback `127.0.0.1:18088` 网关端口，三个测试卷、internal-only 网络，无 DB/API 主机端口或外网默认路由。某些 Docker Desktop 版本不绑定 internal-only 网络的主机端口；内部 runner 不受影响，浏览器补验和受限短生命周期桥接说明见 [apitest 指南](../apitest/README.md)。不要为此把数据库或 API 发布到主机或给替身开外网。

runner 按 URL/方法发现 23 个脚本，以只读、限时、限行 reader 对照 PostgreSQL，成功退出 0；任何失败/空套件退出非零并生成脱敏 HTML。报告默认 `apitest/reports/<timestamp>.html`，与 artifacts/runtime 数据一起被 Git 忽略，不得提交。完整启动、支持自测、无效输出/503 分支及真实 Swagger 浏览器补验命令见上述指南；替身通过不等于真实模型质量评估。

## 数据库迁移与健康检查

数据库迁移仅由一次性的 `migrate` 服务执行：

```sh
docker compose --env-file .env run --rm migrate
```

API 依赖数据库迁移和种子数据初始化成功完成后才能启动。

公开的健康检查端点会检查：

* 是否能够完成一次数据库往返访问和 retrieval schema 迁移检查；
* 教学资料存储位置是否可写；
* retrieval schema、indexer freshness/queue、Qdrant 配置，以及 embedding/generation 是否已配置或处于 degraded。

health 不会调用模型、不发送真实问题或资料，也不返回凭据、请求头、prompt、正文或 provider 原始错误。模型/Qdrant degraded 不会让普通资料列表、元数据或下载不可用。

该端点只会返回少量、不包含敏感信息的响应；它绝不会返回密码、数据库连接字符串或 HMAC 密钥。

生产环境回滚时，应恢复相互协调的数据库备份和教学资料备份。

不要在运行中的生产部署上使用初始迁移所提供的破坏性降级操作。该迁移明确规定，降级操作仅用于空部署或演示部署。

## 创建真实账户

系统目前没有实现用户自助注册和密码找回功能。

应通过容器化 CLI 创建教师或学生账户。该命令会以交互方式提示输入密码，因此密码不会出现在命令行参数中：

```sh
docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps api \
  campusclaw create-user \
    --account teacher.physics \
    --class-name Physics-2026 \
    --role teacher \
    --create-class
```

如果需要为已有班级创建学生账户，可以使用相同命令，并将角色设置为：

```sh
--role student
```

服务器会：

* 创建或选择唯一的班级成员关系；
* 校验用户角色；
* 使用 Argon2id 对密码进行哈希；
* 拒绝重复账户。

绝不要通过密码参数传递密码，不要使用 `echo` 输出密码，也不要将密码保存在 Shell 历史记录文件中。

账户创建完成后，仅在确有必要时才需要重启服务；API 会直接从 PostgreSQL 中读取新账户。

已签发的 JWT 会在配置的生命周期结束时过期；用户状态、角色和班级仍会在每次受保护请求中由服务器重新读取。注销只清除浏览器中的本地 Token，不能逐一撤销已签发的 JWT。

## HTTPS、JWT 与密钥

* 生产环境必须在外部反向代理或网关处终止 TLS，并将 HTTPS 流量转发至已经发布的 Web 网关。
* 登录成功后，浏览器将 JWT Access Token 保存至 `localStorage`，并只通过同源 API 的 `Authorization: Bearer` 请求头发送；Token 不会写入 URL，也不使用认证 Cookie。
* `JWT_SIGNING_KEY` 必须具有不可预测性，并且长度至少为 32 字节。`JWT_ACCESS_TOKEN_LIFETIME_SECONDS` 必须保持有界（默认 8 小时）；轮换签名密钥会使全部已签发 Token 失效。
* localStorage 会受到 XSS 窃取风险影响。不得渲染不受信任 HTML，必须保持网关 CSP，并在怀疑泄露时轮换签名密钥、要求用户重新登录。
* PostgreSQL 凭据、JWT 签名密钥、示例账户密码以及部署环境配置文件均属于仅限服务器端使用的敏感信息。
* 上传文件会被强制作为附件下载，不会由应用以内联形式渲染，也不会被应用执行。

## 数据卷生命周期

正常情况下，重新创建服务或容器不会导致数据丢失：

```sh
docker compose --env-file .env up -d --force-recreate
```

进行维护时，如果需要停止服务但保留数据卷，可以运行：

```sh
docker compose --env-file .env stop web api
```

`docker compose down` 会删除容器和网络，但通常会保留具名数据卷。

而：

```sh
docker compose down -v
```

会永久删除 PostgreSQL 数据卷和教学资料数据卷。

因此，该命令只能用于明确希望彻底销毁当前部署的情况，或者用于相互隔离的验收测试项目。

在执行任何数据卷操作之前，都应保留数据库和教学资料备份。

## 协调一致的备份与恢复

数据库和教学资料数据卷共同构成一个逻辑备份单元。

执行备份时，应安排维护窗口，停止 Web/API 的写入操作，并在开始任何备份之前记录 Compose 项目名称和数据卷名称。

在仍有文件上传操作进行时，不要分别独立备份数据库和教学资料。

首先创建权限受限的备份目录：

```sh
mkdir -p backups/$(date +%Y%m%d-%H%M%S)

chmod 700 backups backups/**
```

停止写入服务，并以 PostgreSQL 自定义格式生成数据库转储：

```sh
docker compose --env-file .env stop web api

docker compose --env-file .env exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom \
  > backups/<timestamp>/database.dump
```

随后使用一个临时辅助容器，对具名的教学资料数据卷进行归档。

将 `<project>` 替换为 `docker compose ls` 所显示的 Compose 项目名称，并在执行归档前确认源数据卷：

```sh
docker volume inspect <project>_materials-data

docker run --rm --user 0 \
  -v <project>_materials-data:/source:ro \
  -v "$PWD/backups/<timestamp>":/backup \
  campusclaw-api:local python -c \
  'import tarfile; archive=tarfile.open("/backup/materials.tar.gz", "w:gz"); archive.add("/source", arcname="."); archive.close()'
```

记录数据库转储文件和教学资料归档文件的校验和，并将这些校验和与备份文件一同保存：

```sh
sha256sum backups/<timestamp>/database.dump backups/<timestamp>/materials.tar.gz \
  > backups/<timestamp>/SHA256SUMS
```

执行恢复时，应继续保持上传维护窗口处于启用状态。

首先创建一份新的回滚备份。

然后，在相同的数据库 Schema 版本下恢复 PostgreSQL，并将教学资料归档恢复至同一个具名数据卷：

```sh
docker compose --env-file .env exec -T db \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists --no-owner --exit-on-error \
  < backups/<timestamp>/database.dump

docker run --rm --user 0 \
  -v <project>_materials-data:/target \
  -v "$PWD/backups/<timestamp>":/backup \
  campusclaw-api:local python -c \
  'import pathlib, shutil, tarfile; root=pathlib.Path("/target"); [shutil.rmtree(p) if p.is_dir() else p.unlink() for p in root.iterdir()]; tarfile.open("/backup/materials.tar.gz").extractall(root, filter="data")'
```

恢复完成后，重新启动服务，并在重新开放外部流量之前完成验证：

```sh
docker compose --env-file .env up -d api web

curl -fsS http://localhost:${WEB_PORT:-8080}/health

python tests/check_backup_restore.py
```

恢复检查会将数据库中教学资料对应的 `storage_key` 和 SHA-256 元数据与恢复后的实际文件进行比较，同时验证种子账户数量和教学资料数量。

如果发现任何文件缺失，或者文件摘要值不一致，应保持应用停止状态，并恢复此前创建的回滚备份。

## 本学期范围限制与非目标

本学期的实现有意保留以下限制：

* 仅支持一个 API 写入实例，并使用本地具名数据卷进行文件存储；不支持 API 横向扩展，也不支持共享对象存储。
* 不提供 OCR、Office 文档解析、图片/音频/视频转写、恶意软件扫描、内容执行或内联渲染功能。
* 支持有界持久化多轮引导聊天，但不提供自主 Agent 规划、模型工具调用、模型选择班级范围、跨会话记忆或无限历史。
* 不提供作业提交、学情诊断、教案/命题生成、教学资料编辑、删除、版本管理、分享链接或用户注册功能。
* 支持创建者维护的解题引导技能与多个独立智能体；不提供密码找回、外部身份提供商、账户管理界面、任意可执行技能/工具、MCP、多智能体协作或知识图谱。
* 每个账户只能属于一个班级，并且教师只能访问其所属班级。

以上内容均属于明确规定的本学期非目标，而不是未公开的待办功能。

任何功能范围的扩展，都必须在实施之前同步更新 OpenSpec 的提案、设计、规格说明和任务。
