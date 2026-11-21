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
  await expect(page.getByText("查询条件")).toBeVisible()
})

test("notification page is read-only", async ({ page }) => {
  await page.goto("/notifications")
  await expect(page.getByRole("heading", { name: "通知" })).toBeVisible()
  await expect(page.getByRole("button", { name: /标记已读/ })).toHaveCount(0)
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
  await page.getByRole("button", { name: "保存", exact: true }).click()
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
  await page.getByRole("button", { name: "保存", exact: true }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  await expect(
    page.getByRole("button", { name: new RegExp(name) }),
  ).toBeVisible()
})
