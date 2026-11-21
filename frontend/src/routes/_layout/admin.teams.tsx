import { createFileRoute } from "@tanstack/react-router"

import { TeamsPage } from "@/features/admin/teams/TeamsPage"

export const Route = createFileRoute("/_layout/admin/teams")({
  component: TeamsPage,
  head: () => ({ meta: [{ title: "Team 与成员 - 工单派发系统" }] }),
})
