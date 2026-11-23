import { RefreshCw, TriangleAlert, X } from "lucide-react"

import { Button } from "@/components/ui/button"

export type ConflictSnapshot = {
  version?: number
  statusLabel?: string
}

const knownConflictMessages: Record<string, string> = {
  STALE_VERSION: "该资源已被其他用户更新，已加载最新版本。",
  NO_ELIGIBLE_HANDLER: "当前 Team 没有合格处理人，请检查成员和可用状态。",
  DUPLICATE_ASSIGNMENT: "该工单已经派发给当前处理人，无需重复派发。",
  IDEMPOTENCY_KEY_CONFLICT: "本次提交与先前请求不一致，请重新发起操作。",
}

export function ConflictBanner({
  message,
  code,
  refreshed,
  before,
  after,
  onDismiss,
}: {
  message: string
  code?: string
  refreshed: boolean
  before?: ConflictSnapshot
  after?: ConflictSnapshot
  onDismiss?: () => void
}) {
  const displayMessage = (code && knownConflictMessages[code]) || message
  const versionDiff =
    before?.version !== undefined || after?.version !== undefined
      ? `v${before?.version ?? "?"} → ${
          after?.version !== undefined ? `v${after.version}` : "读取中…"
        }`
      : null
  const statusDiff =
    before?.statusLabel || after?.statusLabel
      ? `${before?.statusLabel ?? "未知状态"} → ${
          after?.statusLabel ?? "读取中…"
        }`
      : null

  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/8 px-4 py-3"
      role="alert"
      data-testid="conflict-banner"
    >
      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-amber-700 dark:text-amber-300" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">资源已发生变化</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{displayMessage}</p>
        {versionDiff || statusDiff ? (
          <div className="mt-2 grid gap-1 rounded-md border border-amber-500/20 bg-background/45 px-3 py-2 font-mono text-xs">
            {versionDiff ? <p>版本 {versionDiff}</p> : null}
            {statusDiff ? <p>状态 {statusDiff}</p> : null}
          </div>
        ) : null}
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
