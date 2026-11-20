import { type APIRequestContext, expect, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomEmail, randomPassword, randomTeamName } from "./utils/random.ts"
import { logInUser } from "./utils/user.ts"

const apiBaseUrl = "http://localhost:8000/api/v1"

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

  await expect(page.getByRole("heading", { name: "工单中心" })).toBeVisible()
  await expect(page.getByText("按当前账号可见范围查询工单")).toBeVisible()
  await expect(page.getByRole("button", { name: "新建工单" })).toBeVisible()
})

test("Notification center is available to the current recipient", async ({
  page,
}) => {
  await page.goto("/notifications")

  await expect(page.getByRole("heading", { name: "通知中心" })).toBeVisible()
  await expect(page.getByText("仅展示当前账号接收的通知")).toBeVisible()
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
  await expect(page.getByRole("link", { name: "返回工单中心" })).toBeVisible()
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

  await page.getByLabel("新评论").fill("刷新版本后成功提交")
  await page.getByRole("button", { name: "发布评论" }).click()
  await expect(page.getByText("刷新版本后成功提交")).toBeVisible()
})

test("Admin and handler complete the end-to-end ticket flow", async ({
  page,
  browser,
  request,
}) => {
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

  await page.getByRole("combobox", { name: "处理人" }).click()
  await page.getByRole("option", { name: new RegExp(handlerName) }).click()
  await page.getByRole("button", { name: "人工派发" }).click()
  await expect(page.getByText("待接受")).toBeVisible()

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
  await handlerPage.getByRole("button", { name: "确认" }).click()
  await expect(handlerPage.getByText("待确认")).toBeVisible()

  await page.reload()
  await page.getByRole("button", { name: "关闭工单" }).click()
  await page.getByLabel("操作说明").fill("E2E 验收通过")
  await page.getByRole("button", { name: "确认" }).click()
  await expect(page.getByText("已关闭")).toBeVisible()
  await expect(
    page.getByTestId("ticket-timeline").getByText("工单已关闭"),
  ).toBeVisible()
})
