## 1. 红色主题基础

- [x] 1.1 在 `frontend/src/styles.css` 中建立红色主题、文字、表面、边框、阴影和焦点环设计令牌，并确认不再以现有绿色作为主交互色
- [x] 1.2 重构登录、页头、表单、资料卡片和操作控件样式，覆盖 hover、active、focus-visible、disabled、loading、error 与 empty 状态，并在桌面和不大于 600px 的视口确认无横向溢出

## 2. 页面呈现与中文交互

- [x] 2.1 调整 `frontend/src/auth.tsx` 的登录页呈现结构，将登录及进行中文案改为 `登录`/`登录中…`，并通过认证单元测试确认请求、回跳和失败处理保持不变
- [x] 2.2 调整 `frontend/src/materials.tsx` 的资料库页层级，将刷新、上传、下载和退出操作改为规定中文文案，并通过资料库单元测试确认教师/学生控件可见性及下载地址保持不变
- [x] 2.3 调整 `frontend/src/materials.tsx` 的上传页层级，将上传、进行中和返回操作改为规定中文文案，并通过上传单元测试确认 FormData、CSRF 请求头和成功导航保持不变

## 3. 测试与验收

- [x] 3.1 更新 `frontend/src/*.test.tsx` 与 `frontend/e2e/demo.spec.ts` 中依赖英文操作文案的断言，并运行 `npm test` 验证中文控件及原有交互行为
- [x] 3.2 在 `frontend/` 运行 `npm run lint`、`npm run typecheck` 和 `npm run build`，确认静态检查与生产构建全部通过
- [x] 3.3 在可用演示环境运行 `npm run test:e2e`，并实看登录、教师资料库、学生资料库和上传页的红色主题、中文操作、键盘焦点及移动端重排；记录任何受环境限制未执行的项目
  - 环境记录：Compose 演示栈的既有 `migrate` 容器因缺少 `psycopg2` 无法启动，故未执行依赖真实后端的 `npm run test:e2e`；已使用 Vite + Playwright 网络模拟完成 1440×1000 与 390×844 的登录、教师资料库、学生空状态和上传页实看，确认无横向溢出、焦点环可见且角色操作正确。
- [x] 3.4 运行 `openspec validate --changes --strict`，确认本变更规约与实现任务保持有效且完整
