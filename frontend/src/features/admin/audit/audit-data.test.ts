import { describe, expect, it } from "vitest"

import { getAuditActionLabel, getAuditEntityLabel } from "./audit-data"

describe("audit presentation", () => {
  it("maps stable audit codes to readable Chinese labels", () => {
    expect(getAuditActionLabel("ASSIGNMENT_REJECTED")).toBe("派发被拒绝")
    expect(getAuditActionLabel("AUTO_ASSIGN_FAILED")).toBe("自动派发失败")
    expect(getAuditEntityLabel("TEAM_MEMBERSHIP")).toBe("Team 成员")
  })
})
