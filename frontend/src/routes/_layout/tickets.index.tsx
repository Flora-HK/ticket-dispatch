import { createFileRoute } from "@tanstack/react-router"

import type { TicketStatus } from "@/client"
import {
  TicketListPage,
  type TicketListSearch,
} from "@/features/tickets/TicketListPage"

export const Route = createFileRoute("/_layout/tickets/")({
  validateSearch: (search: Record<string, unknown>): TicketListSearch => ({
    team_id: typeof search.team_id === "string" ? search.team_id : undefined,
    submitter_id:
      typeof search.submitter_id === "string" ? search.submitter_id : undefined,
    status:
      typeof search.status === "string"
        ? (search.status as TicketStatus)
        : undefined,
    assigned_to_me:
      search.assigned_to_me === true || search.assigned_to_me === "true"
        ? true
        : undefined,
    created_from:
      typeof search.created_from === "string" ? search.created_from : undefined,
    created_to:
      typeof search.created_to === "string" ? search.created_to : undefined,
    sort: typeof search.sort === "string" ? search.sort : undefined,
  }),
  component: TicketsPage,
  head: () => ({ meta: [{ title: "工单中心 - 工单派发系统" }] }),
})

function TicketsPage() {
  const search = Route.useSearch()
  return <TicketListPage search={search} />
}
