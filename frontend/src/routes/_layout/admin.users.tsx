import { createFileRoute } from "@tanstack/react-router"

import { UsersPage } from "@/features/admin/users/UsersPage"

export const Route = createFileRoute("/_layout/admin/users")({
  component: UsersPage,
  head: () => ({ meta: [{ title: "用户与角色 - 工单派发系统" }] }),
})
