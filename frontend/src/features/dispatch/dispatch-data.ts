import type { DispatchCandidatePublic } from "@/client"

export type CandidateComparison = {
  handlerId: string
  name: string
  rank: number
  load: number
  lastAssignedAt: string | null
  loadDelta: number
}

export function buildCandidateComparisons(
  candidates: readonly DispatchCandidatePublic[],
): CandidateComparison[] {
  if (candidates.length === 0) return []

  // 候选差值统一相对当前最低负载，便于人工派发时直接比较。
  const minimumLoad = Math.min(
    ...candidates.map((candidate) => candidate.open_ticket_count),
  )
  return candidates.map((candidate) => ({
    handlerId: candidate.handler_id,
    name:
      candidate.handler.full_name ||
      candidate.handler.email ||
      candidate.handler_id.slice(0, 8),
    rank: candidate.rank,
    load: candidate.open_ticket_count,
    lastAssignedAt: candidate.last_assigned_at,
    loadDelta: candidate.open_ticket_count - minimumLoad,
  }))
}

export function dispatchActionLabel(
  mode: "MANUAL" | "AUTO",
  candidateName: string | null,
): string {
  if (mode === "AUTO") return "按最低负载自动派发"
  return candidateName ? `派发给 ${candidateName}` : "选择处理人"
}

export function formatCandidateLastAssignedAt(value: string | null): string {
  if (!value) return "从未派发"
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value))
}
