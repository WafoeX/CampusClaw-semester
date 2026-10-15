import { expect, test, type Page } from "@playwright/test";
import { agent, answer, conversation, events, frames, historical, ids } from "../src/test/chat-fixtures";

function password(role: string): string {
  const value = process.env[`DEMO_${role}_PASSWORD`];
  if (!value) throw new Error(`Missing synthetic test credential: DEMO_${role}_PASSWORD`);
  return value;
}
async function login(page: Page, account: string, secret: string) {
  await page.goto("/login");
  await page.getByLabel("Account").fill(account); await page.getByLabel("Password").fill(secret);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Teaching materials" })).toBeVisible();
}

// Actual deployed API, migration, seeded identity and Nginx stream path; no provider is needed for a no-evidence turn.
test("teacher management → student chat/config update → soft delete → creator audit through the real gateway", async ({ page, browser }) => {
  const suffix = `${Date.now()}`;
  const name = `引导导师 ${suffix}`;
  const skillName = `解题引导 ${suffix}`;
  await login(page, "teacher.alpha", password("ALPHA_TEACHER"));
  await page.getByRole("link", { name: "我的智能体与技能" }).click();
  await page.getByLabel("技能名称").fill(skillName);
  await page.getByLabel("技能指令").fill("给出提示、步骤和追问，不直接给最终答案。");
  await page.getByRole("button", { name: "保存技能", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("技能已保存");
  await page.getByLabel("智能体名称").fill(name);
  await page.getByLabel("教师提示词").fill("引导学生基于课程证据逐步检查条件。");
  await page.getByLabel(skillName, { exact: true }).check();
  await page.getByRole("button", { name: "保存智能体", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("智能体已保存");
  await page.getByRole("button", { name: `发布 ${name}`, exact: true }).click();
  await expect(page.getByRole("status")).toContainText("发布状态已更新");
  const auditHref = await page.getByRole("link", { name: `审计 ${name}`, exact: true }).getAttribute("href");
  expect(auditHref).toBeTruthy();

  const studentContext = await browser.newContext();
  const student = await studentContext.newPage();
  await login(student, "student.alpha", password("ALPHA_STUDENT"));
  await student.getByRole("link", { name: "智能体与会话", exact: true }).click();
  await student.getByRole("button", { name: `与 ${name} 创建会话`, exact: true }).focus();
  await student.keyboard.press("Enter");
  await expect(student.getByRole("heading", { name: `智能体会话 · ${name}`, exact: true })).toBeFocused();
  const conversationPath = new URL(student.url()).pathname;
  await student.getByLabel("当前问题", { exact: true }).fill(`无匹配证据问题 ${suffix}`);
  await student.getByRole("button", { name: "发送消息", exact: true }).focus();
  await student.keyboard.press("Enter");
  await expect(student.getByRole("status")).toHaveText("回答已完成。");
  await expect(student.getByLabel("当前问题", { exact: true })).toBeFocused();
  await expect(student.getByRole("article", { name: "智能体消息 2", exact: true })).toContainText("根据本班资料无法回答该问题");
  await expect(student.getByRole("status")).toHaveAttribute("aria-live", "polite");

  await page.getByRole("button", { name: `编辑 ${name}`, exact: true }).click();
  await expect(page.getByLabel("智能体名称", { exact: true })).toBeFocused();
  await page.getByLabel("教师提示词").fill("更新配置：先追问条件，再给出有证据的提示。");
  await page.getByRole("button", { name: "保存智能体", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("智能体已保存");
  if (await page.getByRole("button", { name: `发布 ${name}`, exact: true }).count()) {
    await page.getByRole("button", { name: `发布 ${name}`, exact: true }).click();
    await expect(page.getByRole("status")).toContainText("发布状态已更新");
  }
  await student.getByLabel("当前问题").fill(`另一个无证据问题 ${suffix}`);
  await student.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(student.getByRole("status")).toHaveText("回答已完成。");
  await expect(student.getByRole("article", { name: "智能体消息 4", exact: true })).toContainText("智能体配置已更新");
  await student.reload();
  await expect(student.getByRole("article", { name: "智能体消息 4", exact: true })).toContainText("根据本班资料无法回答该问题");
  await student.getByRole("link", { name: "返回会话列表", exact: true }).click();
  await student.getByRole("button", { name: `删除 ${name} 的会话`, exact: true }).click();
  await expect(student.getByRole("button", { name: "取消删除", exact: true })).toBeFocused();
  await expect(student.getByRole("region", { name: "确认删除会话？" })).toContainText("教师仍可审计您的身份、问题、回答和引用");
  await student.keyboard.press("Tab"); await student.keyboard.press("Enter");
  await expect(student.getByRole("button", { name: `删除 ${name} 的会话`, exact: true })).toHaveCount(0);
  await expect(student.getByRole("heading", { name: "智能体与会话", exact: true })).toBeFocused();
  await student.goto(conversationPath);
  await expect(student.getByRole("alert")).toContainText("资源不存在或无权访问");

  await page.goto(auditHref!);
  await page.getByLabel("审计状态").selectOption("true");
  await page.getByRole("link", { name: `student.alpha · ${name}`, exact: true }).click();
  await expect(page.getByText(/学生：student.alpha/)).toContainText("学生已删除（保留审计）");
  await expect(page.getByRole("article", { name: "智能体消息 4", exact: true })).toContainText("根据本班资料无法回答该问题");
  await expect(page.getByRole("form", { name: "发送消息", exact: true })).toHaveCount(0);
  const auditPath = new URL(page.url()).pathname;
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await login(other, "teacher.beta", password("BETA_TEACHER"));
  await other.goto(auditPath);
  await expect(other.getByRole("alert")).toContainText("资源不存在或无权访问");
  await expect(other.getByRole("list", { name: "会话消息" })).toHaveCount(0);
  await otherContext.close(); await studentContext.close();
});

async function mockedStudent(page: Page, body: string) {
  await page.addInitScript(() => localStorage.setItem("campusclaw.access-token", "synthetic-browser-fixture"));
  await page.route("**/api/**", async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    expect(request.headers()["authorization"]).toBe("Bearer synthetic-browser-fixture");
    if (path.endsWith("/messages")) {
      expect(request.postDataJSON()).toEqual({ content: "引导问题" });
      await route.fulfill({ contentType: "text/event-stream", body }); return;
    }
    if (path.endsWith("/download")) { await route.fulfill({ contentType: "text/plain", headers: { "Content-Disposition": 'attachment; filename="notes.txt"' }, body: "synthetic material" }); return; }
    const data = path === "/api/auth/me" ? { user_id: ids.user, class_id: ids.material, account: "student.fixture", role: "student" }
      : path === "/api/agents" ? [{ id: agent.id, name: agent.name, description: agent.description }]
      : path.startsWith(`/api/conversations/${ids.conversation}`) ? conversation : [];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
  });
  await page.goto(`/conversations/${ids.conversation}`);
  await expect(page.getByRole("status")).toHaveText("已刷新服务器记录。");
}

test("keyboard citation navigation, live status, safe text and authenticated download on a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const browserErrors: string[] = []; page.on("pageerror", error => browserErrors.push(error.message));
  await mockedStudent(page, frames());
  await page.getByLabel("当前问题").fill("引导问题");
  await page.getByRole("button", { name: "发送消息", exact: true }).focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toHaveText("回答已完成。");
  await expect(page.getByRole("article", { name: "智能体消息 2", exact: true })).toContainText(answer);
  await expect(page.locator(".message-history img, .message-history script")).toHaveCount(0);
  await expect(page.getByLabel("当前问题")).toBeFocused();
  await page.getByRole("link", { name: "[S1]", exact: true }).focus(); await page.keyboard.press("Enter");
  await expect(page.locator(`#message-${ids.assistant}-source-S1`)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "下载授权资料 S1" })).toBeFocused();
  const downloaded = page.waitForEvent("download"); await page.keyboard.press("Enter");
  expect((await downloaded).suggestedFilename()).toBe("notes.txt");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(browserErrors).toEqual([]);
});

test("interrupted browser streams require explicit refresh and never resubmit", async ({ page }) => {
  let posts = 0;
  page.on("request", request => { if (request.method() === "POST" && request.url().endsWith("/messages")) posts++; });
  await mockedStudent(page, frames(events().slice(0, 2)));
  await page.getByLabel("当前问题").fill("引导问题"); await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("连接中断");
  await expect(page.getByRole("button", { name: "发送消息", exact: true })).toBeDisabled();
  await page.route(`**/api/conversations/${ids.conversation}?*`, route => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...conversation, messages: [historical] }) }));
  await page.getByRole("button", { name: "刷新服务器记录（不会重发）" }).click();
  await expect(page.getByRole("link", { name: "[S1]", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "发送消息", exact: true })).toBeEnabled();
  expect(posts).toBe(1);
});
