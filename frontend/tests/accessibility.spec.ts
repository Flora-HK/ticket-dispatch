import AxeBuilder from "@axe-core/playwright"
import { expect, test } from "@playwright/test"

for (const path of [
  "/",
  "/dispatch",
  "/tickets",
  "/notifications",
  "/admin/users",
  "/admin/teams",
  "/admin/audit",
]) {
  test(`axe serious and critical violations are absent on ${path}`, async ({
    page,
  }) => {
    await page.goto(path)
    await page.waitForLoadState("networkidle")

    const results = await new AxeBuilder({ page }).analyze()
    const violations = results.violations.filter((violation) =>
      ["serious", "critical"].includes(violation.impact ?? ""),
    )
    expect(violations).toEqual([])
  })
}
