import { describe, expect, it } from "vitest"

import {
  getActiveTicketFilters,
  type TicketListSearch,
} from "./ticket-filter-data"

describe("ticket filters", () => {
  it("summarizes active filters for removable chips", () => {
    const search: TicketListSearch = {
      team_id: "team-1",
      status: "PENDING_ASSIGNMENT",
      assigned_to_me: true,
      created_from: "2026-11-01",
    }

    expect(
      getActiveTicketFilters(search, [{ id: "team-1", name: "运营支持" }]).map(
        (item) => item.label,
      ),
    ).toEqual(["运营支持", "待派发", "只看我的", "创建于 2026-11-01 后"])
  })

  it("does not treat sorting as an active filter", () => {
    expect(getActiveTicketFilters({ sort: "created_at:desc" }, [])).toEqual([])
  })
})
