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
  await expect(page.getByText("工单派发概览")).toBeVisible()
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
  await expect(page.getByText("Invalid email address")).toBeVisible()
})

test("Logout returns to login and protects ticket routes", async ({ page }) => {
  await page.goto("/login")
  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL("/")

  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "Log Out" }).click()
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
