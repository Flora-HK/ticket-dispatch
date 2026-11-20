import type { TicketStatus } from "@/client"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

import { ticketStatusLabels } from "./ticket-ui"

const statusClassNames: Record<TicketStatus, string> = {
  PENDING_ASSIGNMENT:
    "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  ASSIGNED: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  IN_PROGRESS:
    "border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300",
  PENDING_CONFIRMATION:
    "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  CLOSED: "border-zinc-500/30 bg-zinc-500/10 text-zinc-600 dark:text-zinc-300",
}

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  return (
    <Badge className={cn(statusClassNames[status])}>
      {ticketStatusLabels[status]}
    </Badge>
  )
}
