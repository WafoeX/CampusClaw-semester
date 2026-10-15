# 隔离 API 验收框架

`cases/` 包含 23 个按 URL/方法独立组织的正式黑盒脚本，覆盖登录、旧知识查询、
技能/智能体管理、发布、学生会话与创建者审计、SSE 消息和公开文档。
请求只经过测试网关，持久化断言使用只读观察角色；不导入业务实现或白盒 TestClient。
**空套件或未匹配的操作选择必须失败，不能把支持层自测当作完整 API 验收通过。**

## 启动与清理

从仓库根目录运行，Docker Compose v2：

```sh
mkdir -p apitest/reports
export APITEST_UID="$(id -u)" APITEST_GID="$(id -g)"
docker compose -f docker-compose.apitest.yml build
docker compose -f docker-compose.apitest.yml up -d --wait
# 支持层自测（迁移、索引、权限、真实网关/替身/SSE/DB）
docker compose -f docker-compose.apitest.yml run --rm --no-deps apitest \
  python -m unittest apitest.tests.stack_checks -v
# 列出 23 个正式操作
docker compose -f docker-compose.apitest.yml run --rm --no-deps apitest \
  python apitest/run_all.py --list
# 正式验收入口；任何案例失败则返回 1 并继续收集后续结果
docker compose -f docker-compose.apitest.yml run --rm --no-deps apitest
# 只清理这一独立测试项目，包含其测试数据
docker compose -f docker-compose.apitest.yml down --volumes
```

不要用 `-f docker-compose.yml -f docker-compose.apitest.yml` 合并配置，不要指向现有数据库。
默认项目名 `campusclaw-apitest`；三个卷均带该项目前缀，无 external 卷。
唯一宿主机端口为 `127.0.0.1:18088`（可用 `APITEST_PORT` 调整端口），
Swagger 为 `http://127.0.0.1:18088/api/docs`。DB/API/Qdrant/替身不映射宿主机端口。
所有服务仅加入 `internal: true` 测试网络，没有外网默认路由。

迁移 → 合成班级/账户/资料 → Qdrant 与替身就绪 → 索引 → API → 网关依赖按序执行。
`indexer` 是一次性任务；准备后新增资料需要再次运行 indexer。
测试替身不含任何外部 HTTP 客户端，固定嵌入维度 8，模型失败由 fixture model 控制而非问题文本。
正常、拒答、无效 JSON、HTTP 503 分别为 `fixture-guidance`、`fixture-refusal`、
`fixture-malformed`、`fixture-failure`，不使用真实模型。默认模型 `fixture-delayed`
与正常输出相同，但固定延迟 2 秒，让收到 message.started 后的并发冲突验证可重复。
模型只能由测试服务环境变量 `APITEST_GENERATION_MODEL` 选择，不由用户问题触发。

## 数据与权限

数据库固定为 `campusclaw_apitest`，迁移/应用使用非超级用户 `apitest_owner`。
引导管理员仅在空测试卷初始化角色及 `pg_trgm`。
runner 只取得 `apitest_reader` 连接，不获得管理员/owner 密码环境变量；
它没有写权限、建库/建角色/建表权限，也无权读取 `users.password_hash`。
客户端仅允许主机 `db`、该数据库名与 reader 角色，拒绝 URL 额外参数。
SQL 使用 `LiteralString` 与独立参数，每次事务只读；5 秒 statement timeout，
2 秒 lock timeout，单次最多 1000 行。观察权限仅限测试库，不得复用于正式环境。

四个样本账户 `teacher.alpha`、`student.alpha`、`teacher.beta`、`student.beta`，
以及同班非创建者 `teacher.alpha.other`、另一学生 `student.alpha.other`，
密码均为显式合成值 `apitest-account-only`，经应用 Argon2 哈希入库。
`ALPHA_FERN` 与 `BETA_CRYSTAL` 是完全合成、分属两班的索引事实。
每次运行用 `context.fixtures.name("skill")` 等生成 UUID run-scoped 名称，避免互相污染。
测试清理由删除独立 Compose 卷完成，不在 runner 内开放写库或 TRUNCATE。

## 操作脚本契约

例如 `apitest/cases/api/agents/{agent_id}/GET.py`，目录按 URL 逐段镜像，
文件名只允许大写 GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS。
每个模块只有一个 `OPERATION`，路径与方法必须严格匹配目录/文件名。
仅参数名不同的重复路由也拒绝。共享逻辑不放进 `cases/`。

```python
from apitest.support import Operation


def run(context, checks):
    status, body = context.client.json("GET", "/health")
    checks.require(status == 200, "response.status")
    checks.require(isinstance(body, dict), "response.schema")


OPERATION = Operation("GET", "/health", run)
```

上述为最小契约示例。正式脚本各自建立 run-scoped 前置数据，不依赖执行顺序。
共享 `scenarios.py` 只负责 HTTP 前置数据、根据公开 OpenAPI 验证响应以及只读 SQL 核对，
不把多个操作的验收调度合并到一个脚本。
`Client.login()` 返回 token 供调用者内存使用；`Client.json()` 校验 JSON 媒体类型。
`parse_sse()` / `parse_sse_chunks()` 校验 UTF-8、心跳、帧、顺序、连续序号、共同 ID、
终态唯一性、摘要、引用集合与下载路径；不支持自动续传或自动重发。
`context.database.rows("SELECT ... WHERE id = %s", (identifier,))` 用于只读一致性断言。

## 报告与脱敏

默认输出 `apitest/reports/<UTC时间戳>.html`，另可用 `--report` 指定。
报告使用标准库生成，无外链、脚本或运行时内容，动态文字 HTML 转义，包含方法、URL、
通过/失败/异常、时长及断言标识。失败继续运行后续案例，最终返回 1。

**不要把 actual/expected 值放进断言标签。** 仅 `support.SAFE_LABELS` 中经过审计的固定标识
可进入报告，其他字符串一律替换成 `assertion_failed`；异常只记 `case_crashed`。
用例导入与运行期间 stdout/stderr 丢弃，不打印异常对象、HTTP body、SQL/DSN、token、
密码、提示词、历史、材料或原始模型响应。默认没有泄露内容的 debug 模式。
每个案例最多 100 个诊断，成功标签去重以保留最后的数据库/脱敏断言类别。
报告及 `.runtime/`、`artifacts/` 全部 Git 忽略。
脚本为受信任仓库代码，不是用来运行敌意 Python 的安全沙箱。

## 无服务自测与静态检查

```sh
api/.venv/bin/python -m unittest \
  apitest.tests.test_harness apitest.tests.test_clients apitest.tests.test_stub \
  apitest.tests.test_cases -v
api/.venv/bin/ruff check --config api/pyproject.toml apitest
api/.venv/bin/ruff format --check --config api/pyproject.toml apitest
api/.venv/bin/python -m apitest.check_types
uvx pyright --project apitest/pyrightconfig.json
```

URL 中 `{agent_id}`、`openapi.json` 不是 Python 包名；多个 GET.py 一次传给 mypy
会重名。`check_types` 对支持模块一批检查、对每个操作独立严格检查，不排除任何案例，
不放宽规则。继续保留现有 `api/tests/` 与前端测试，本框架不会替代它们。

## 流开始后的失败验收

主套件默认验证成功、精确拒答、当前引用、修订变化、并发 409、预流 JSON 错误及 DB 一致性。
下列补充命令复用同一个消息操作脚本；切换的是测试 API 的服务端模型，不修改资料/用户或观察角色权限。
每次 API 重建后必须等健康，再重启 Nginx，避免其缓存旧容器 IP。

```sh
export APITEST_UID="$(id -u)" APITEST_GID="$(id -g)"
export APITEST_GENERATION_MODEL=fixture-malformed
docker compose -f docker-compose.apitest.yml up -d --wait --no-deps api
docker compose -f docker-compose.apitest.yml restart gateway
docker compose -f docker-compose.apitest.yml up -d --wait --no-deps gateway
docker compose -f docker-compose.apitest.yml run --rm --no-deps \
  -e APITEST_EXPECT_MESSAGE_ERROR=generation_invalid apitest \
  python apitest/run_all.py --operation 'POST /api/conversations/{conversation_id}/messages' \
  --report apitest/reports/invalid-output.html

export APITEST_GENERATION_MODEL=fixture-failure
docker compose -f docker-compose.apitest.yml up -d --wait --no-deps api
docker compose -f docker-compose.apitest.yml restart gateway
docker compose -f docker-compose.apitest.yml up -d --wait --no-deps gateway
docker compose -f docker-compose.apitest.yml run --rm --no-deps \
  -e APITEST_EXPECT_MESSAGE_ERROR=answer_generation_unavailable apitest \
  python apitest/run_all.py --operation 'POST /api/conversations/{conversation_id}/messages' \
  --report apitest/reports/provider-failure.html

# 恢复默认延迟正常模型，再执行全套
unset APITEST_GENERATION_MODEL
docker compose -f docker-compose.apitest.yml up -d --wait --no-deps api
docker compose -f docker-compose.apitest.yml restart gateway
docker compose -f docker-compose.apitest.yml up -d --wait --no-deps gateway
docker compose -f docker-compose.apitest.yml run --rm --no-deps apitest
```

错误分支断言仅有 started/error、无 answer.delta、错误码 allowlist、无泄露，以及一条用户消息、
一条 failed assistant、空正文与空引用；失败模式报告不是完整 23 操作报告。
`--operation 'METHOD /path'` 精确选择注册路径，不改变 `--cases` 的 URL 根目录。

## 可选真实 Chromium Swagger 验收

已有前端 Playwright 依赖和 Chromium 时，从仓库根执行：

```sh
node apitest/browser_swagger.mjs
```

它实际点击登录 Try it out、Authorize、身份 Try it out，断言同一 principal、恰好一个
Bearer 头、无页面/控制台错误、无外部请求。截图前刷新以清除 token/响应/curl 面板，
仅保存 `artifacts/task9-swagger.png` 和不含内容的布尔结果。HTTP 文档脚本不会假称操作了 UI。
某些 Docker Desktop 版本不为 internal-only 网络绑定宿主端口；脚本在本地连接不可达时，
核对独立测试项目标签，临时用 loopback TCP → docker exec/nc → 同一个 gateway 转发。
不会给容器接入外网网络、映射 DB/API 或联系其他服务；结束时关闭转发与浏览器。
不要把这个环境限制误报成直接宿主端口验收通过。
