import { createFileRoute } from "@tanstack/react-router"

import { AuditPage } from "@/features/admin/audit/AuditPage"

export const Route = createFileRoute("/_layout/admin/audit")({
  component: AuditPage,
  head: () => ({ meta: [{ title: "审计查询 - 工单派发系统" }] }),
})
