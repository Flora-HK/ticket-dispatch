import { test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

const pages = [
  ["overview", "/", true],
  ["dispatch", "/dispatch", true],
  ["tickets", "/tickets", true],
  ["notifications", "/notifications", true],
  ["admin-users", "/admin/users", false],
  ["admin-teams", "/admin/teams", false],
  ["admin-audit", "/admin/audit", false],
] as const

async function signInAsDispatcher(page: import("@playwright/test").Page) {
  await page.goto("/login")
  await page.evaluate(() => localStorage.removeItem("access_token"))
  await page.reload()
  await page.getByTestId("email-input").fill("demo.dispatcher@example.com")
  await page.getByTestId("password-input").fill("Demo-dispatch-2026!")
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL("/")
}

for (const [name, path, asDispatcher] of pages) {
  test(`capture ${name}`, async ({ page }, testInfo) => {
    if (asDispatcher) await signInAsDispatcher(page)
    await page.goto(path)
    await page.waitForLoadState("networkidle")
    await page.screenshot({
      path: `playwright/screenshots/${name}-${testInfo.project.name}.png`,
      fullPage: true,
    })
  })
}

test("capture dark overview", async ({ page }, testInfo) => {
  await signInAsDispatcher(page)
  await page.evaluate(() => localStorage.setItem("vite-ui-theme", "dark"))
  await page.reload()
  await page.waitForLoadState("networkidle")
  await page.screenshot({
    path: `playwright/screenshots/overview-dark-${testInfo.project.name}.png`,
    fullPage: true,
  })
})

test("capture ticket detail", async ({ page, request }, testInfo) => {
  const login = await request.post(
    "http://localhost:8000/api/v1/login/access-token",
    {
      form: {
        username: firstSuperuser,
        password: firstSuperuserPassword,
      },
    },
  )
  const token = (await login.json()).access_token as string
  const tickets = await request.get(
    "http://localhost:8000/api/v1/tickets?limit=1&sort=updated_at:desc",
    { headers: { Authorization: `Bearer ${token}` } },
  )
  const ticket = (await tickets.json()).items[0] as { id: string }

  await signInAsDispatcher(page)
  await page.goto(`/tickets/${ticket.id}`)
  await page.waitForLoadState("networkidle")
  await page.screenshot({
    path: `playwright/screenshots/ticket-detail-${testInfo.project.name}.png`,
    fullPage: true,
  })
})
