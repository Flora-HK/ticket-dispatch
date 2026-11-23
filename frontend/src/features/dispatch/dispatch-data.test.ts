import { describe, expect, it } from "vitest"

import type { DispatchCandidatePublic } from "@/client"

import {
  buildCandidateComparisons,
  dispatchActionLabel,
  formatCandidateLastAssignedAt,
} from "./dispatch-data"

function candidate(
  rank: number,
  load: number,
  lastAssignedAt: string | null,
): DispatchCandidatePublic {
  return {
    handler_id: `handler-${rank}`,
    handler: {
      id: `handler-${rank}`,
      email: `handler-${rank}@example.com`,
      full_name: `处理人 ${rank}`,
      is_active: true,
    },
    rank,
    open_ticket_count: load,
    last_assigned_at: lastAssignedAt,
  }
}

describe("dispatch data", () => {
  it("compares every candidate with the lowest current load", () => {
    expect(
      buildCandidateComparisons([
        candidate(1, 0, null),
        candidate(2, 3, "2026-11-22T10:00:00Z"),
      ]).map((item) => ({
        name: item.name,
        load: item.load,
        delta: item.loadDelta,
      })),
    ).toEqual([
      { name: "处理人 1", load: 0, delta: 0 },
      { name: "处理人 2", load: 3, delta: 3 },
    ])
  })

  it("names the selected manual dispatch target in the primary action", () => {
    expect(dispatchActionLabel("MANUAL", "林晨")).toBe("派发给 林晨")
    expect(dispatchActionLabel("MANUAL", null)).toBe("选择处理人")
    expect(dispatchActionLabel("AUTO", null)).toBe("按最低负载自动派发")
  })

  it("formats the latest assignment compactly for the comparison row", () => {
    expect(formatCandidateLastAssignedAt(null)).toBe("从未派发")
    expect(formatCandidateLastAssignedAt("2026-11-21T14:27:00Z")).toBe(
      "11/21 22:27",
    )
  })
})
