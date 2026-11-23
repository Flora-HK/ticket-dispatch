import type { TicketPage, TicketStatus, TicketSummaryPublic } from "@/client"

export type OverviewTicket = TicketSummaryPublic

export type CandidateLoad = {
  handler_id: string
  open_ticket_count: number
}

export type OverviewException = {
  code: "PENDING_OVER_24H" | "CONFIRMATION_OVER_48H" | "WORKLOAD_SKEW"
  count: number
  label: string
}

export type OverviewSnapshot = {
  counts: Record<TicketStatus, number>
  pending: OverviewTicket[]
  exceptions: OverviewException[]
  partial: boolean
}

// 零负载不绘制正长度负载条，避免把无负载误读为有负载。
export function workloadBarWidth(load: number, maxLoad: number): number {
  if (load <= 0) return 0
  return Math.max(8, (load / Math.max(1, maxLoad)) * 100)
}

function elapsedMinutes(updatedAt: string, now: Date): number {
  return Math.max(
    0,
    Math.floor((now.getTime() - new Date(updatedAt).getTime()) / 60_000),
  )
}

export function formatWaitDuration(
  updatedAt: string,
  now = new Date(),
): string {
  const minutes = elapsedMinutes(updatedAt, now)
  if (minutes < 1) return "刚刚"
  if (minutes < 60) return `${minutes} 分钟`

  const totalHours = Math.floor(minutes / 60)
  if (totalHours < 24) {
    const remainder = minutes % 60
    return remainder
      ? `${totalHours} 小时 ${remainder} 分`
      : `${totalHours} 小时`
  }

  const days = Math.floor(totalHours / 24)
  const remainder = totalHours % 24
  return remainder ? `${days} 天 ${remainder} 小时` : `${days} 天`
}

export function isPendingOverdue(updatedAt: string, now = new Date()): boolean {
  return elapsedMinutes(updatedAt, now) >= 24 * 60
}

export function summarizeWorkload(loads: readonly number[]) {
  if (loads.length === 0) {
    return { min: 0, max: 0, delta: 0, skewed: false }
  }
  const min = Math.min(...loads)
  const max = Math.max(...loads)
  const delta = max - min
  return { min, max, delta, skewed: delta >= 3 }
}

export async function collectTicketPages(
  fetchPage: (cursor?: string | null) => Promise<TicketPage>,
  options: { maxItems: number },
): Promise<{ items: OverviewTicket[]; partial: boolean }> {
  const items: OverviewTicket[] = []
  let cursor: string | null | undefined

  do {
    const page = await fetchPage(cursor)
    const remaining = options.maxItems - items.length
    items.push(...page.items.slice(0, remaining))
    cursor = page.next_cursor
  } while (cursor && items.length < options.maxItems)

  return { items, partial: Boolean(cursor) }
}

function hoursSince(value: string, now: Date): number {
  return (now.getTime() - new Date(value).getTime()) / 3_600_000
}

export function buildOverviewSnapshot(
  tickets: OverviewTicket[],
  candidateGroups: CandidateLoad[][] = [],
  now = new Date(),
  partial = false,
): OverviewSnapshot {
  const counts: Record<TicketStatus, number> = {
    PENDING_ASSIGNMENT: 0,
    ASSIGNED: 0,
    IN_PROGRESS: 0,
    PENDING_CONFIRMATION: 0,
    CLOSED: 0,
  }

  for (const ticket of tickets) {
    counts[ticket.status] += 1
  }

  const pendingOver24h = tickets.filter(
    (ticket) =>
      ticket.status === "PENDING_ASSIGNMENT" &&
      hoursSince(ticket.updated_at, now) >= 24,
  ).length
  const confirmationOver48h = tickets.filter(
    (ticket) =>
      ticket.status === "PENDING_CONFIRMATION" &&
      hoursSince(ticket.updated_at, now) >= 48,
  ).length
  const skewedTeams = candidateGroups.filter((candidates) => {
    if (candidates.length < 2) return false
    const loads = candidates.map((candidate) => candidate.open_ticket_count)
    return Math.max(...loads) - Math.min(...loads) >= 3
  }).length

  const exceptions: OverviewException[] = []
  if (pendingOver24h > 0) {
    exceptions.push({
      code: "PENDING_OVER_24H",
      count: pendingOver24h,
      label: "待派发超过 24 小时",
    })
  }
  if (confirmationOver48h > 0) {
    exceptions.push({
      code: "CONFIRMATION_OVER_48H",
      count: confirmationOver48h,
      label: "待确认超过 48 小时",
    })
  }
  if (skewedTeams > 0) {
    exceptions.push({
      code: "WORKLOAD_SKEW",
      count: skewedTeams,
      label: "团队负载差异较大",
    })
  }

  return {
    counts,
    pending: tickets
      .filter((ticket) => ticket.status === "PENDING_ASSIGNMENT")
      .sort((left, right) => left.updated_at.localeCompare(right.updated_at)),
    exceptions,
    partial,
  }
}
