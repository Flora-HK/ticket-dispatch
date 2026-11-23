import { expect, test } from "@playwright/test"

import { apiBaseUrl } from "./config.ts"

async function openDispatchableTicket(page: import("@playwright/test").Page) {
  await page.goto("/dispatch")
  const ticketId = await page.evaluate(async (apiBase) => {
    const token = localStorage.getItem("access_token")
    const headers = { Authorization: `Bearer ${token}` }
    const response = await fetch(
      `${apiBase}/tickets?status=PENDING_ASSIGNMENT&limit=100&sort=updated_at:asc`,
      { headers },
    )
    const tickets = (await response.json()).items
    for (const ticket of tickets) {
      const candidates = await fetch(
        `${apiBase}/tickets/${ticket.id}/dispatch-candidates`,
        { headers },
      )
      if (!candidates.ok) continue
      const data = await candidates.json()
      if (data.items.length > 0) return ticket.id
    }
    throw new Error("No dispatchable ticket with candidates was found")
  }, apiBaseUrl)
  await page.goto(`/dispatch?ticket=${ticketId}`)
}

test("dispatcher overview exposes the A, B and C work areas", async ({
  page,
}, testInfo) => {
  await page.goto("/")

  await expect(page.getByRole("heading", { name: "派发总览" })).toBeVisible()
  await expect(page.getByTestId("priority-queue")).toBeVisible()
  await expect(
    page.locator("[data-testid='queue-wait-time']:visible").first(),
  ).toBeVisible()
  await expect(page.getByTestId("workload-panel")).toBeVisible()
  await expect(page.getByTestId("exception-panel")).toBeVisible()
  if (testInfo.project.name !== "chromium") {
    await page.getByRole("button", { name: "打开导航" }).click()
  }
  await expect(page.getByRole("link", { name: /派发工作台/ })).toBeVisible()
})

test("clicking a priority queue row opens the ticket detail", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "desktop table interaction")
  await page.goto("/")

  const queue = page.getByTestId("priority-queue")
  const tableOverflow = await queue
    .locator("[data-slot='table-container']")
    .evaluate((element) => element.scrollWidth - element.clientWidth)
  expect(tableOverflow).toBe(0)

  const row = queue.locator("tbody tr").first()
  const teamCell = await row.locator("td").nth(1).boundingBox()
  if (!teamCell) throw new Error("Priority queue row is not visible")
  await page.mouse.click(
    teamCell.x + teamCell.width / 2,
    teamCell.y + teamCell.height / 2,
  )

  await expect(page).toHaveURL(/\/tickets\/[0-9a-f-]+$/)
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
})

test("dispatch workbench offers candidate comparison and auto mode", async ({
  page,
}, testInfo) => {
  await openDispatchableTicket(page)

  await expect(page.getByRole("heading", { name: "派发工作台" })).toBeVisible()
  if (testInfo.project.name === "mobile-chromium") {
    await page.getByRole("tab", { name: /派发/ }).click()
  }
  await expect(page.getByTestId("candidate-ranking")).toBeVisible()
  await expect(page.getByText("最近派发").first()).toBeVisible()
  await page
    .getByRole("radiogroup", { name: "候选处理人" })
    .locator("label")
    .first()
    .click()
  await expect(page.getByRole("button", { name: /派发给/ })).toBeVisible()
  await page.getByRole("button", { name: "自动派发", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "按最低负载自动派发" }),
  ).toBeVisible()
})

test("dispatch workbench stages the mobile decision flow", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium")
  await page.goto("/dispatch")

  await expect(page.getByRole("tab", { name: /队列/ })).toBeVisible()
  await page.getByRole("tab", { name: /详情/ }).click()
  await expect(page.getByRole("tab", { name: /详情/ })).toHaveAttribute(
    "aria-selected",
    "true",
  )
})

test("ticket filters are represented in the URL", async ({ page }) => {
  await page.goto("/tickets")
  await expect(page.getByLabel("提交人 ID")).toHaveCount(0)
  await expect(page.getByRole("button", { name: "更多筛选" })).toHaveAttribute(
    "aria-expanded",
    "false",
  )
  await page.getByRole("combobox", { name: "状态" }).click()
  await page.getByRole("option", { name: "待派发" }).click()

  await expect(page).toHaveURL(/status=PENDING_ASSIGNMENT/)
  await expect(
    page.getByRole("button", { name: "移除筛选 待派发" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "移除筛选 待派发" }).click()
  await expect(page).not.toHaveURL(/status=PENDING_ASSIGNMENT/)
  await page.getByRole("button", { name: "更多筛选" }).click()
  await expect(page.getByText("只看派发给我的工单")).toBeVisible()
})
