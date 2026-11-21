import { describe, expect, it } from "vitest"

import {
  buildOverviewSnapshot,
  collectTicketPages,
  type OverviewTicket,
} from "./overview-data"

function ticket(
  id: string,
  status: OverviewTicket["status"],
  updatedAt: string,
): OverviewTicket {
  return {
    id,
    team_id: "team-1",
    team: { id: "team-1", name: "账号与权限" },
    submitter_id: "user-1",
    submitter: {
      id: "user-1",
      email: "submitter@example.com",
      full_name: "测试提交人",
      is_active: true,
    },
    title: id,
    status,
    version: 1,
    created_at: updatedAt,
    updated_at: updatedAt,
  }
}

describe("overview data", () => {
  it("marks aggregation as partial when the item cap is reached", async () => {
    const result = await collectTicketPages(
      async (cursor) => ({
        items: [
          ticket(
            cursor ? "ticket-3" : "ticket-1",
            "PENDING_ASSIGNMENT",
            "2026-11-21T10:00:00Z",
          ),
        ],
        next_cursor: cursor ? null : "cursor-2",
      }),
      { maxItems: 1 },
    )

    expect(result.items.map((item) => item.id)).toEqual(["ticket-1"])
    expect(result.partial).toBe(true)
  })

  it("identifies stale work and workload skew", () => {
    const snapshot = buildOverviewSnapshot(
      [
        ticket("pending-old", "PENDING_ASSIGNMENT", "2026-11-20T07:00:00Z"),
        ticket("confirm-old", "PENDING_CONFIRMATION", "2026-11-19T07:00:00Z"),
      ],
      [
        [
          { handler_id: "h1", open_ticket_count: 5 },
          { handler_id: "h2", open_ticket_count: 1 },
        ],
      ],
      new Date("2026-11-21T12:00:00Z"),
    )

    expect(snapshot.counts.PENDING_ASSIGNMENT).toBe(1)
    expect(snapshot.counts.PENDING_CONFIRMATION).toBe(1)
    expect(snapshot.exceptions.map((item) => item.code)).toEqual([
      "PENDING_OVER_24H",
      "CONFIRMATION_OVER_48H",
      "WORKLOAD_SKEW",
    ])
  })
})
