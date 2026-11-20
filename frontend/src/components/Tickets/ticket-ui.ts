import type { TicketStatus } from "@/client"

export const ticketStatusLabels = {
  PENDING_ASSIGNMENT: "待派发",
  ASSIGNED: "待接受",
  IN_PROGRESS: "处理中",
  PENDING_CONFIRMATION: "待确认",
  CLOSED: "已关闭",
} satisfies Record<TicketStatus, string>

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
