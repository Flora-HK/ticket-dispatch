import { createFileRoute } from "@tanstack/react-router"

import { TicketDetailPage as TicketDetailView } from "@/features/tickets/TicketDetailPage"

export const Route = createFileRoute("/_layout/tickets/$ticketId")({
  component: TicketDetailPage,
})

function TicketDetailPage() {
  const { ticketId } = Route.useParams()
  return <TicketDetailView ticketId={ticketId} />
}
