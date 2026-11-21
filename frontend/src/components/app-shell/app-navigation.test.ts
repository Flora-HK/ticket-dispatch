import { describe, expect, it } from "vitest"

import { navigationForRoles } from "./app-navigation"

describe("role-aware navigation", () => {
  it("gives dispatchers the primary operations navigation", () => {
    const titles = navigationForRoles(["DISPATCHER"]).flatMap((group) =>
      group.items.map((item) => item.title),
    )

    expect(titles).toEqual(["总览", "派发工作台", "工单", "通知"])
  })

  it("keeps administration separate for admins", () => {
    const groups = navigationForRoles(["ADMIN"])

    expect(groups.map((group) => group.title)).toEqual(["工作", "管理"])
    expect(groups[1]?.items.map((item) => item.title)).toEqual([
      "用户与角色",
      "Team 与成员",
      "审计查询",
    ])
  })

  it("does not expose dispatch or governance to handlers", () => {
    const titles = navigationForRoles(["HANDLER"]).flatMap((group) =>
      group.items.map((item) => item.title),
    )

    expect(titles).not.toContain("派发工作台")
    expect(titles).not.toContain("用户与角色")
  })
})
