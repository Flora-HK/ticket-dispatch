import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { StatusBadge } from "./StatusBadge"

describe("StatusBadge", () => {
  it("renders readable text for a pending ticket status", () => {
    render(<StatusBadge kind="ticket" value="PENDING_ASSIGNMENT" />)

    expect(screen.getByText("待派发")).toBeInTheDocument()
    expect(screen.getByText("待派发")).toHaveAttribute(
      "data-status",
      "PENDING_ASSIGNMENT",
    )
  })

  it("falls back to the raw value for an unknown status", () => {
    render(<StatusBadge kind="ticket" value="UNKNOWN_STATUS" />)

    expect(screen.getByText("UNKNOWN_STATUS")).toBeInTheDocument()
  })
})
