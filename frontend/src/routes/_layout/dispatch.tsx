import { createFileRoute } from "@tanstack/react-router"

import { DispatchWorkbench } from "@/features/dispatch/DispatchWorkbench"

type DispatchSearch = {
  ticket?: string
}

export const Route = createFileRoute("/_layout/dispatch")({
  validateSearch: (search: Record<string, unknown>): DispatchSearch => ({
    ticket: typeof search.ticket === "string" ? search.ticket : undefined,
  }),
  component: DispatchPage,
  head: () => ({ meta: [{ title: "派发工作台 - 工单派发系统" }] }),
})

function DispatchPage() {
  const { ticket } = Route.useSearch()
  return <DispatchWorkbench initialTicketId={ticket} />
}
