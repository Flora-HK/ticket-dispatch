import type { TicketAction } from "@/client"

const ticketActionLabels: Record<TicketAction, string> = {
  EDIT: "编辑工单",
  DISPATCH: "进入派发",
  COMMENT: "添加评论",
  ACCEPT: "接受工单",
  REJECT: "拒绝派发",
  COMPLETE: "完成处理",
  CLOSE: "关闭工单",
  REOPEN: "重新打开",
}

export function hasTicketAction(
  detail: { allowed_actions: readonly TicketAction[] },
  action: TicketAction,
): boolean {
  return detail.allowed_actions.includes(action)
}

export function getTicketActionLabel(action: TicketAction): string {
  return ticketActionLabels[action]
}

export function createSubmissionKey(): string {
  return crypto.randomUUID()
}
