import { expect, type Page, test } from "@playwright/test"

import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomPassword } from "./utils/random.ts"

test.use({ storageState: { cookies: [], origins: [] } })

const fillForm = async (page: Page, email: string, password: string) => {
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
}

test("Login form contains only contract-supported actions", async ({
  page,
}) => {
  await page.goto("/login")

  await expect(page.getByTestId("email-input")).toBeVisible()
  await expect(page.getByTestId("password-input")).toBeVisible()
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Forgot your password?" }),
  ).toHaveCount(0)
  await expect(page.getByRole("link", { name: "Sign up" })).toHaveCount(0)
})

test("Valid credentials open the ticket workspace", async ({ page }) => {
  await page.goto("/login")
  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL("/")
  await expect(page.getByRole("heading", { name: "派发总览" })).toBeVisible()
})

test("Invalid credentials show the unified API error", async ({ page }) => {
  await page.goto("/login")
  await fillForm(page, firstSuperuser, randomPassword())
  await page.getByRole("button", { name: "登录" }).click()
  await expect(
    page.getByText("The email or password is incorrect."),
  ).toBeVisible()
})

test("Invalid email is rejected before submission", async ({ page }) => {
  await page.goto("/login")
  await fillForm(page, "invalidemail", firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()
  await expect(page.getByText("请输入有效邮箱地址")).toBeVisible()
})

test("Logout returns to login and protects ticket routes", async ({
  page,
}, testInfo) => {
  await page.goto("/login")
  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL("/")

  if (testInfo.project.name !== "chromium") {
    await page.getByRole("button", { name: "打开导航" }).click()
  }
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "退出登录" }).click()
  await page.waitForURL("/login")

  await page.goto("/tickets")
  await page.waitForURL("/login")
})

test("Invalid token redirects to login", async ({ page }) => {
  await page.goto("/tickets")
  await page.evaluate(() => {
    localStorage.setItem("access_token", "invalid_token")
  })
  await page.goto("/tickets")
  await page.waitForURL("/login")
})
