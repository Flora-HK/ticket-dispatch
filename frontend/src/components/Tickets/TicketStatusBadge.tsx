import type { TicketStatus } from "@/client"
import { StatusBadge } from "@/components/shared/StatusBadge"

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  return <StatusBadge kind="ticket" value={status} />
}
