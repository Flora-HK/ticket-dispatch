import { describe, expect, it } from "vitest"

import {
  expandEnvironmentValue,
  toE2EDatabaseUrl,
} from "../../scripts/e2e-environment.ts"

describe("E2E environment", () => {
  it("derives app_e2e from the development database URL", () => {
    expect(
      toE2EDatabaseUrl(
        "postgresql://postgres:secret@localhost:5432/app?sslmode=disable",
      ),
    ).toBe(
      "postgresql://postgres:secret@localhost:5432/app_e2e?sslmode=disable",
    )
  })

  it("expands the PostgreSQL password placeholder before deriving the URL", () => {
    expect(
      expandEnvironmentValue(
        "postgresql://postgres:$" + "{POSTGRES_PASSWORD}@localhost:5432/app",
        { POSTGRES_PASSWORD: "local-secret" },
      ),
    ).toBe("postgresql://postgres:local-secret@localhost:5432/app")
  })
})
