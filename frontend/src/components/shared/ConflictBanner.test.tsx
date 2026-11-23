import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ConflictBanner } from "./ConflictBanner"

describe("ConflictBanner", () => {
  it("shows the refreshed version range for a conflict", () => {
    render(
      <ConflictBanner
        message="工单已被其他用户更新"
        refreshed
        before={{ version: 1 }}
        after={{ version: 2 }}
      />,
    )

    expect(screen.getByRole("alert")).toBeInTheDocument()
    expect(screen.getByText(/v1 → v2/)).toBeInTheDocument()
  })

  it("localizes known stale-version conflicts", () => {
    render(
      <ConflictBanner
        message="The ticket has changed. Reload and try again."
        code="STALE_VERSION"
        refreshed
      />,
    )

    expect(
      screen.getByText("该资源已被其他用户更新，已加载最新版本。"),
    ).toBeInTheDocument()
    expect(screen.queryByText(/The ticket has changed/)).not.toBeInTheDocument()
  })
})
