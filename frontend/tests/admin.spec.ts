import { expect, test } from "@playwright/test"

import { randomEmail, randomTeamName } from "./utils/random.ts"

test("admin can navigate the three governance areas", async ({
  page,
}, testInfo) => {
  await page.goto("/admin/users")
  await expect(page.getByRole("heading", { name: "用户与角色" })).toBeVisible()
  await expect(page.getByRole("button", { name: "新建账号" })).toBeVisible()

  if (testInfo.project.name === "chromium") {
    await page.getByRole("link", { name: "Team 与成员" }).click()
  } else {
    await page.goto("/admin/teams")
  }
  await expect(page.getByRole("heading", { name: "Team 与成员" })).toBeVisible()
  await expect(page.getByText("运营支持").first()).toBeVisible()

  if (testInfo.project.name === "chromium") {
    await page.getByRole("link", { name: "审计查询" }).click()
  } else {
    await page.goto("/admin/audit")
  }
  await expect(page.getByRole("heading", { name: "审计查询" })).toBeVisible()
  await expect(page.getByRole("combobox", { name: "操作" })).toBeVisible()
  await expect(page.getByText("审计记录", { exact: true })).toBeVisible()
})

test("notification page is read-only", async ({ page }) => {
  await page.goto("/notifications")
  await expect(page.getByRole("heading", { name: "通知" })).toBeVisible()
  await expect(page.getByRole("button", { name: /标记已读/ })).toHaveCount(0)
})

test("audit records expose readable labels before raw details", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "covered on desktop")
  await page.goto("/admin/audit")
  await expect(page.getByText("工单创建").first()).toBeVisible()
  await expect(page.getByRole("button", { name: "更多条件" })).toHaveAttribute(
    "aria-expanded",
    "false",
  )

  await page
    .getByRole("button", { name: /查看审计记录/ })
    .first()
    .click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("查看原始 JSON")).toBeVisible()
  await expect(dialog.getByText("Actor", { exact: true })).toBeVisible()
  await expect(dialog.getByText("执行上下文")).toBeHidden()
  await dialog.getByText("查看原始 JSON").click()
  await expect(dialog.getByText("执行上下文")).toBeVisible()
})

test("admin creates a user through the governance form", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "covered on desktop")
  const email = randomEmail()
  await page.goto("/admin/users")
  await page.getByRole("button", { name: "新建账号" }).click()
  await page.getByLabel("邮箱").fill(email)
  await page.getByLabel("姓名").fill("Playwright 管理台账号")
  await page.getByLabel("初始密码").fill("Strong-demo-pass-2026")

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/users") &&
      response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "创建账号" }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

test("admin creates a team through the governance form", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "covered on desktop")
  const name = randomTeamName()
  await page.goto("/admin/teams")
  await page.getByRole("button", { name: "新建 Team" }).click()
  await page.getByLabel("Team 名称").fill(name)

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/teams") &&
      response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "创建 Team" }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  await expect(page.getByText("Team 已创建")).toBeVisible()
  await expect(page.getByRole("dialog")).toHaveCount(0)
})

test("admin validation errors focus the field summary", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "covered on desktop")
  await page.goto("/admin/users")
  await page.getByRole("button", { name: "新建账号" }).click()
  await page.getByLabel("邮箱").fill("not-an-email")
  await page.getByLabel("初始密码").fill("Strong-demo-pass-2026")

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/users") &&
      response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "创建账号" }).click()
  expect((await responsePromise).status()).toBe(422)

  const summary = page.getByRole("alert").filter({
    hasText: "请检查以下字段",
  })
  await expect(summary).toBeFocused()
  await expect(summary.getByRole("link")).toHaveAttribute("href", "#user-email")
})
