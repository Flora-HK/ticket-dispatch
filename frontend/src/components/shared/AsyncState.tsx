import {
  CircleAlert,
  Inbox,
  LoaderCircle,
  RefreshCw,
  ShieldX,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export function LoadingRows({
  rows = 5,
  className,
}: {
  rows?: number
  className?: string
}) {
  return (
    <div
      className={cn("flex flex-col gap-3 p-5", className)}
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">正在加载</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-4">
          <Skeleton className="size-8 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          <Skeleton className="h-6 w-16 rounded-full" />
        </div>
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string
  description: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex min-h-52 flex-col items-center justify-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      <span className="grid size-10 place-items-center rounded-xl bg-muted text-muted-foreground">
        <Inbox className="size-5" />
      </span>
      <div>
        <p className="font-medium">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}

export function ErrorState({
  title = "加载失败",
  message,
  requestId,
  forbidden = false,
  onRetry,
  className,
}: {
  title?: string
  message: string
  requestId?: string
  forbidden?: boolean
  onRetry?: () => void
  className?: string
}) {
  const Icon = forbidden ? ShieldX : CircleAlert
  return (
    <div
      className={cn(
        "flex min-h-52 flex-col items-center justify-center gap-3 rounded-xl border border-destructive/20 bg-danger-surface px-6 py-10 text-center",
        className,
      )}
      role="alert"
    >
      <Icon className="size-6 text-destructive" />
      <div>
        <p className="font-medium">{title}</p>
        <p className="mt-1 max-w-lg text-sm text-muted-foreground">{message}</p>
        {requestId ? (
          <p className="mt-2 font-mono text-[11px] text-muted-foreground">
            request_id: {requestId}
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" />
          重试
        </Button>
      ) : null}
    </div>
  )
}

export function InlineLoading({ label = "正在加载" }: { label?: string }) {
  return (
    <span
      className="inline-flex items-center gap-2 text-sm text-muted-foreground"
      aria-live="polite"
    >
      <LoaderCircle className="size-4 animate-spin" />
      {label}
    </span>
  )
}
