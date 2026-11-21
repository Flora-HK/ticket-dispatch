import { expect, test } from "@playwright/test"

test("dispatcher overview exposes the A, B and C work areas", async ({
  page,
}, testInfo) => {
  await page.goto("/")

  await expect(page.getByRole("heading", { name: "派发总览" })).toBeVisible()
  await expect(page.getByTestId("priority-queue")).toBeVisible()
  await expect(page.getByTestId("workload-panel")).toBeVisible()
  await expect(page.getByTestId("exception-panel")).toBeVisible()
  if (testInfo.project.name !== "chromium") {
    await page.getByRole("button", { name: "打开导航" }).click()
  }
  await expect(page.getByRole("link", { name: /派发工作台/ })).toBeVisible()
})

test("dispatch workbench offers candidate comparison and auto mode", async ({
  page,
}) => {
  await page.goto("/dispatch")

  await expect(page.getByRole("heading", { name: "派发工作台" })).toBeVisible()
  await expect(page.getByTestId("candidate-ranking")).toBeVisible()
  await page.getByRole("button", { name: "自动派发" }).click()
  await expect(
    page.getByRole("button", { name: "按最低负载自动派发" }),
  ).toBeVisible()
})

test("ticket filters are represented in the URL", async ({ page }) => {
  await page.goto("/tickets")
  await page.getByRole("combobox", { name: "状态" }).click()
  await page.getByRole("option", { name: "待派发" }).click()

  await expect(page).toHaveURL(/status=PENDING_ASSIGNMENT/)
  await expect(page.getByText("只看派发给我的工单")).toBeVisible()
})
