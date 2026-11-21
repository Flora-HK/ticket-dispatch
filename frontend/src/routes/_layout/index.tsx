import { createFileRoute } from "@tanstack/react-router"

import { DispatcherOverview } from "@/features/overview/DispatcherOverview"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "概览 - 工单派发系统",
      },
    ],
  }),
})

function Dashboard() {
  return <DispatcherOverview />
}
