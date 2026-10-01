import { expect, test, type Page } from "@playwright/test";

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required Playwright environment variable: ${name}`);
  return value;
}

const credentials = {
  alphaTeacher: {
    account: "teacher.alpha",
    password: requiredEnv("DEMO_ALPHA_TEACHER_PASSWORD"),
  },
  betaStudent: {
    account: "student.beta",
    password: requiredEnv("DEMO_BETA_STUDENT_PASSWORD"),
  },
};

async function login(page: Page, account: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Account").fill(account);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "登录" }).click();
}

test("unauthenticated protected pages redirect to login", async ({ page }) => {
  await page.goto("/materials");
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fmaterials/);
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
});

test("teacher uploads, sees, downloads, and logs out through the gateway", async ({ page }) => {
  await login(page, credentials.alphaTeacher.account, credentials.alphaTeacher.password);
  await expect(page.getByRole("heading", { name: "Teaching materials" })).toBeVisible();
  await expect(page.getByText("Alpha welcome")).toBeVisible();
  await expect(page.getByText("Beta welcome")).toHaveCount(0);

  await page.getByRole("link", { name: "上传资料" }).click();
  const title = `Gateway lesson ${Date.now()}`;
  await page.getByLabel("Title").fill(title);
  await page.locator('input[type="file"]').setInputFiles({
    name: "gateway-lesson.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("gateway-only material"),
  });
  await page.getByRole("button", { name: "上传资料" }).click();

  await expect(page).toHaveURL(/\/materials$/);
  await expect(page.getByText(title)).toBeVisible();
  const uploadedCard = page.locator(".material-card").filter({ hasText: title });
  const downloadPromise = page.waitForEvent("download");
  await uploadedCard.getByRole("button", { name: /下载文件/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("gateway-lesson.txt");

  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fmaterials/);
});

test("student sees only the beta class and no upload control", async ({ page }) => {
  await login(page, credentials.betaStudent.account, credentials.betaStudent.password);
  await expect(page.getByText("Beta welcome")).toBeVisible();
  await expect(page.getByText("Alpha welcome")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "上传资料" })).toHaveCount(0);
});

test("knowledge Q&A is single-turn, grounded, and citation navigates to a source", async ({ page }) => {
  await page.route("**/api/knowledge/query", async (route) => {
    const request = route.request();
    const body = request.postDataJSON() as Record<string, unknown>;
    expect(body).toEqual({ question: "What is in this lesson?", result_limit: 10, mode: "hybrid" });
    expect(body).not.toHaveProperty("class_id");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "answered",
        answer: "This lesson is grounded [S1]",
        citations: ["S1"],
        requested_mode: "hybrid",
        effective_mode: "hybrid",
        sources: [{ source_id: "S1", material_id: "m1", title: "Alpha welcome", original_filename: "welcome.txt", excerpt: "grounded", page: null, line_start: 1, line_end: 1, section: null, action: "/api/materials/m1/download" }],
      }),
    });
  });
  await login(page, credentials.alphaTeacher.account, credentials.alphaTeacher.password);
  await page.getByLabel("问题").fill("What is in this lesson?");
  await page.getByRole("button", { name: "提交问题" }).click();
  const citation = page.getByRole("link", { name: "[S1]" });
  await expect(citation).toHaveAttribute("href", "#source-S1");
  await citation.click();
  await expect(page.locator("#source-S1")).toBeFocused();
  await expect(page.locator("#source-S1")).toContainText("welcome.txt");
});

test("invalid credentials show a generic error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Account").fill("unknown.account");
  await page.getByLabel("Password").fill("invalid-password");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid account or password");
  await expect(page).toHaveURL(/\/login$/);
});
