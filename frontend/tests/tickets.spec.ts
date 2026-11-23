import { type APIRequestContext, expect, test } from "@playwright/test"

import { apiBaseUrl, firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomEmail, randomPassword, randomTeamName } from "./utils/random.ts"
import { logInUser } from "./utils/user.ts"

async function adminToken(request: APIRequestContext) {
  const response = await request.post(`${apiBaseUrl}/login/access-token`, {
    form: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  expect(response.status()).toBe(200)
  return (await response.json()).access_token as string
}

test("Ticket center is the primary authenticated workspace", async ({
  page,
}) => {
  await page.goto("/tickets")

  await expect(page.getByRole("heading", { name: "工单" })).toBeVisible()
  await expect(page.getByText("按服务端可见范围查询和处理工单")).toBeVisible()
  await expect(page.getByRole("button", { name: "新建工单" })).toBeVisible()
})

test("Notification center is available to the current recipient", async ({
  page,
}) => {
  await page.goto("/notifications")

  await expect(page.getByRole("heading", { name: "通知" })).toBeVisible()
  await expect(page.getByText("仅展示当前账号接收的站内通知")).toBeVisible()
})

test("Retired Items entry is absent from the application shell", async ({
  page,
}) => {
  await page.goto("/tickets")

  await expect(page.getByRole("link", { name: "Items" })).toHaveCount(0)
})

test("Missing tickets render an explicit 404 state", async ({ page }) => {
  await page.goto(`/tickets/${crypto.randomUUID()}`)
  await expect(page.getByText("工单不存在或无权查看")).toBeVisible()
  await expect(page.getByRole("link", { name: "返回工单" })).toBeVisible()
})

test("409 conflict refreshes the ticket before retrying a comment", async ({
  page,
  request,
}) => {
  const token = await adminToken(request)
  const authHeaders = {
    Authorization: `Bearer ${token}`,
    "Idempotency-Key": crypto.randomUUID(),
  }
  const createdTeam = await request.post(`${apiBaseUrl}/teams`, {
    headers: authHeaders,
    data: { name: randomTeamName() },
  })
  expect(createdTeam.status()).toBe(201)
  const team = await createdTeam.json()

  const createdTicket = await request.post(`${apiBaseUrl}/tickets`, {
    headers: {
      ...authHeaders,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: {
      team_id: team.id,
      title: "版本冲突验证工单",
      description: "用于验证前端收到 409 后刷新资源。",
    },
  })
  expect(createdTicket.status()).toBe(201)
  const ticket = await createdTicket.json()

  await page.goto(`/tickets/${ticket.id}`)
  await expect(page.getByText("v1", { exact: true })).toBeVisible()

  const updated = await request.patch(`${apiBaseUrl}/tickets/${ticket.id}`, {
    headers: {
      ...authHeaders,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: {
      title: "版本冲突验证工单（已更新）",
      expected_version: 1,
    },
  })
  expect(updated.status()).toBe(200)

  await page.getByLabel("新评论").fill("第一次使用旧版本提交")
  await page.getByRole("button", { name: "发布评论" }).click()
  await expect(page.getByText("v2", { exact: true })).toBeVisible()
  const conflictBanner = page.getByTestId("conflict-banner")
  await expect(conflictBanner).toContainText("资源已发生变化")
  await expect(conflictBanner).toContainText("v1 → v2")
  await expect(page.getByLabel("新评论")).toHaveValue("第一次使用旧版本提交")

  await page.getByLabel("新评论").fill("刷新版本后成功提交")
  await page.getByRole("button", { name: "发布评论" }).click()
  await expect(page.getByText("刷新版本后成功提交")).toBeVisible()
})

test("Dispatcher completes the automatic dispatch flow", async ({
  page,
  request,
}, testInfo) => {
  const token = await adminToken(request)
  const headers = {
    Authorization: `Bearer ${token}`,
    "Idempotency-Key": crypto.randomUUID(),
  }
  const teamsResponse = await request.get(`${apiBaseUrl}/teams?limit=100`, {
    headers,
  })
  expect(teamsResponse.status()).toBe(200)
  const teams = (await teamsResponse.json()).items as Array<{
    id: string
    name: string
  }>
  const team = teams.find((item) => item.name === "运营支持") ?? teams[0]
  expect(team).toBeTruthy()

  const createdTicket = await request.post(`${apiBaseUrl}/tickets`, {
    headers,
    data: {
      team_id: team.id,
      title: `[E2E] 自动派发 ${Date.now()}`,
      description: "通过 Playwright 验证最低负载自动派发主链路。",
    },
  })
  expect(createdTicket.status()).toBe(201)
  const ticket = await createdTicket.json()

  await page.goto(`/tickets/${ticket.id}`)
  await page.getByRole("link", { name: "进入派发工作台" }).click()
  if (testInfo.project.name === "mobile-chromium") {
    await page.getByRole("tab", { name: /派发/ }).click()
  }
  await page.getByRole("button", { name: "自动派发", exact: true }).click()
  await page.getByRole("button", { name: "按最低负载自动派发" }).click()

  await expect(page.getByTestId("dispatch-explanation")).toBeVisible()
  await expect(
    page.locator("[data-status='ASSIGNED']:visible").first(),
  ).toBeVisible()
})

test("Admin and handler complete the end-to-end ticket flow", async ({
  page,
  browser,
  request,
}, testInfo) => {
  test.setTimeout(90_000)
  const token = await adminToken(request)
  const authHeaders = { Authorization: `Bearer ${token}` }
  const handlerEmail = randomEmail()
  const handlerPassword = randomPassword()
  const handlerName = "E2E 处理人"
  const teamName = randomTeamName()
  const ticketTitle = `E2E 工单 ${Date.now()}`

  const createdUser = await request.post(`${apiBaseUrl}/users`, {
    headers: {
      ...authHeaders,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: {
      email: handlerEmail,
      password: handlerPassword,
      full_name: handlerName,
      roles: ["HANDLER"],
    },
  })
  expect(createdUser.status()).toBe(201)
  const handler = await createdUser.json()

  const createdTeam = await request.post(`${apiBaseUrl}/teams`, {
    headers: {
      ...authHeaders,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: { name: teamName },
  })
  expect(createdTeam.status()).toBe(201)
  const team = await createdTeam.json()

  const membership = await request.put(
    `${apiBaseUrl}/teams/${team.id}/members/${handler.id}`,
    {
      headers: {
        ...authHeaders,
        "Idempotency-Key": crypto.randomUUID(),
      },
      data: {
        is_available: true,
        expected_team_version: team.version,
      },
    },
  )
  expect(membership.status()).toBe(200)

  await page.goto("/tickets")
  await page.getByRole("button", { name: "新建工单" }).click()
  await page.getByRole("combobox", { name: "Team" }).click()
  await page.getByRole("option", { name: teamName }).click()
  await page.getByLabel("标题").fill(ticketTitle)
  await page
    .getByLabel("描述")
    .fill("通过 Playwright 验证完整的派发与处理闭环。")
  await page.getByRole("button", { name: "创建", exact: true }).click()
  await page.waitForURL(/\/tickets\/[0-9a-f-]+$/)
  const ticketId = page.url().split("/").pop()
  expect(ticketId).toBeTruthy()

  await page.getByRole("link", { name: "进入派发工作台" }).click()
  if (testInfo.project.name === "mobile-chromium") {
    await page.getByRole("tab", { name: /派发/ }).click()
  }
  await page
    .getByRole("radiogroup", { name: "候选处理人" })
    .locator("label")
    .filter({ hasText: handlerName })
    .click()
  await page.getByRole("button", { name: `派发给 ${handlerName}` }).click()
  await expect(
    page.locator("[data-status='ASSIGNED']:visible").first(),
  ).toBeVisible()
  await page.goto(`/tickets/${ticketId}`)

  const handlerContext = await browser.newContext({
    storageState: { cookies: [], origins: [] },
  })
  const handlerPage = await handlerContext.newPage()
  await handlerPage.goto("/login")
  await expect(handlerPage.getByTestId("email-input")).toBeVisible()
  await logInUser(handlerPage, handlerEmail, handlerPassword)
  await handlerPage.goto("/notifications")
  await expect(handlerPage.getByText("你收到一个新工单").first()).toBeVisible()

  await handlerPage.goto(`/tickets/${ticketId}`)
  await handlerPage.getByRole("button", { name: "接受工单" }).click()
  await expect(handlerPage.getByText("处理中")).toBeVisible()

  await handlerPage.getByRole("button", { name: "完成处理" }).click()
  await handlerPage.getByLabel("操作说明").fill("E2E 处理已完成")
  await handlerPage.getByRole("button", { name: "提交完成结果" }).click()
  await expect(handlerPage.getByText("待确认")).toBeVisible()

  await page.reload()
  await page.getByRole("button", { name: "关闭工单" }).click()
  await page.getByLabel("操作说明").fill("E2E 验收通过")
  await page.getByRole("button", { name: "确认关闭" }).click()
  await expect(page.locator('[data-status="CLOSED"]').first()).toBeVisible()
  await expect(
    page.getByTestId("ticket-timeline").getByText("工单已关闭"),
  ).toBeVisible()
})
