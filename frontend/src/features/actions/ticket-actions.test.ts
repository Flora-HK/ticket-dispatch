import { describe, expect, it } from "vitest"

import { getTicketActionLabel, hasTicketAction } from "./ticket-actions"

describe("ticket actions", () => {
  it("uses only the server action list for ticket capabilities", () => {
    const detail = { allowed_actions: ["COMMENT"] as const }

    expect(hasTicketAction(detail, "COMMENT")).toBe(true)
    expect(hasTicketAction(detail, "DISPATCH")).toBe(false)
  })

  it("provides concise Chinese labels for action controls", () => {
    expect(getTicketActionLabel("DISPATCH")).toBe("进入派发")
    expect(getTicketActionLabel("ACCEPT")).toBe("接受工单")
  })
})
