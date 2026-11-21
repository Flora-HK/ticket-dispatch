import { createFileRoute } from "@tanstack/react-router"

import { NotificationsPage as NotificationsView } from "@/features/notifications/NotificationsPage"

export const Route = createFileRoute("/_layout/notifications")({
  component: NotificationsPage,
  head: () => ({ meta: [{ title: "通知中心 - 工单派发系统" }] }),
})

function NotificationsPage() {
  return <NotificationsView />
}
