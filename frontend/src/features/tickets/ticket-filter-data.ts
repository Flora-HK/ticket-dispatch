import type { TicketStatus } from "@/client"
import { ticketStatusLabels } from "@/components/Tickets/ticket-ui"

export type TicketListSearch = {
  team_id?: string
  submitter_id?: string
  status?: TicketStatus
  assigned_to_me?: boolean
  created_from?: string
  created_to?: string
  sort?: string
}

export type ActiveTicketFilter = {
  key: Exclude<keyof TicketListSearch, "sort">
  label: string
}

export function getActiveTicketFilters(
  search: TicketListSearch,
  teams: ReadonlyArray<{ id: string; name: string }>,
): ActiveTicketFilter[] {
  const result: ActiveTicketFilter[] = []
  if (search.team_id) {
    result.push({
      key: "team_id",
      label:
        teams.find((team) => team.id === search.team_id)?.name ?? "指定 Team",
    })
  }
  if (search.status) {
    result.push({
      key: "status",
      label: ticketStatusLabels[search.status],
    })
  }
  if (search.assigned_to_me) {
    result.push({ key: "assigned_to_me", label: "只看我的" })
  }
  if (search.submitter_id) {
    result.push({
      key: "submitter_id",
      label: `提交人 ${search.submitter_id.slice(0, 8)}`,
    })
  }
  if (search.created_from) {
    result.push({
      key: "created_from",
      label: `创建于 ${search.created_from} 后`,
    })
  }
  if (search.created_to) {
    result.push({
      key: "created_to",
      label: `创建于 ${search.created_to} 前`,
    })
  }
  return result
}
