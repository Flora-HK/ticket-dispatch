import { RefreshCw, TriangleAlert, X } from "lucide-react"

import { Button } from "@/components/ui/button"

export function ConflictBanner({
  message,
  refreshed,
  onDismiss,
}: {
  message: string
  refreshed: boolean
  onDismiss?: () => void
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/8 px-4 py-3"
      role="alert"
    >
      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-amber-700 dark:text-amber-300" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">资源已发生变化</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{message}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {refreshed
            ? "已加载最新版本，请确认后重新操作。"
            : "正在加载最新版本…"}
        </p>
      </div>
      {onDismiss ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-8 shrink-0"
          aria-label="关闭冲突提示"
          onClick={onDismiss}
        >
          <X className="size-4" />
        </Button>
      ) : (
        <RefreshCw className="mt-1 size-4 shrink-0 text-muted-foreground" />
      )}
    </div>
  )
}
