import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export type StatusKind = "ticket" | "assignment" | "role" | "audit"

const labels: Record<string, string> = {
  PENDING_ASSIGNMENT: "待派发",
  ASSIGNED: "待接受",
  IN_PROGRESS: "处理中",
  PENDING_CONFIRMATION: "待确认",
  CLOSED: "已关闭",
  ACCEPTED: "已接受",
  REJECTED: "已拒绝",
  COMPLETED: "已完成",
  SUPERSEDED: "已替代",
  SUBMITTER: "提交人",
  DISPATCHER: "派单员",
  HANDLER: "处理人",
  ADMIN: "管理员",
  SUCCESS: "成功",
  FAILED: "失败",
}

const badgeClasses: Record<string, string> = {
  PENDING_ASSIGNMENT:
    "border-status-pending/35 bg-status-pending/12 text-amber-800 dark:text-amber-200",
  ASSIGNED:
    "border-status-assigned/35 bg-status-assigned/12 text-blue-800 dark:text-blue-200",
  IN_PROGRESS:
    "border-status-progress/35 bg-status-progress/12 text-violet-800 dark:text-violet-200",
  ACCEPTED:
    "border-status-progress/35 bg-status-progress/12 text-violet-800 dark:text-violet-200",
  PENDING_CONFIRMATION:
    "border-status-confirmation/35 bg-status-confirmation/12 text-emerald-800 dark:text-emerald-200",
  COMPLETED:
    "border-status-confirmation/35 bg-status-confirmation/12 text-emerald-800 dark:text-emerald-200",
  CLOSED:
    "border-status-closed/30 bg-status-closed/10 text-zinc-700 dark:text-zinc-300",
  REJECTED:
    "border-destructive/30 bg-destructive/10 text-red-800 dark:text-red-200",
  SUPERSEDED: "border-border bg-muted text-muted-foreground",
  SUBMITTER: "border-sky-500/20 bg-sky-500/8 text-sky-800 dark:text-sky-200",
  DISPATCHER:
    "border-blue-500/20 bg-blue-500/8 text-blue-800 dark:text-blue-200",
  HANDLER:
    "border-violet-500/20 bg-violet-500/8 text-violet-800 dark:text-violet-200",
  ADMIN: "border-rose-500/20 bg-rose-500/8 text-rose-800 dark:text-rose-200",
  SUCCESS:
    "border-status-confirmation/30 bg-status-confirmation/10 text-emerald-800 dark:text-emerald-200",
  FAILED:
    "border-destructive/30 bg-destructive/10 text-red-800 dark:text-red-200",
}

export function StatusBadge({
  kind: _kind,
  value,
}: {
  kind: StatusKind
  value: string
}) {
  return (
    <Badge
      data-status={value}
      variant="outline"
      className={cn("rounded-md px-2 py-0.5 font-medium", badgeClasses[value])}
    >
      {labels[value] ?? value}
    </Badge>
  )
}
