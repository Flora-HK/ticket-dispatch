import { CircleAlert, RefreshCw, X } from "lucide-react"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"

export function ActionError({
  title = "操作未完成",
  message,
  requestId,
  onRetry,
  onDismiss,
}: {
  title?: string
  message: string
  requestId?: string
  onRetry?: () => void
  onDismiss?: () => void
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-destructive/25 bg-danger-surface px-4 py-3"
      role="alert"
    >
      <CircleAlert className="mt-0.5 size-5 shrink-0 text-destructive" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{message}</p>
        {requestId ? (
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            request_id: {requestId}
          </p>
        ) : null}
        {onRetry ? (
          <Button
            className="mt-3"
            variant="outline"
            size="sm"
            onClick={onRetry}
          >
            <RefreshCw />
            重试
          </Button>
        ) : null}
      </div>
      {onDismiss ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-8 shrink-0"
          aria-label="关闭错误提示"
          onClick={onDismiss}
        >
          <X className="size-4" />
        </Button>
      ) : null}
    </div>
  )
}

export function FormErrorSummary({
  title = "请检查以下字段",
  errors,
  fieldIdPrefix,
  fieldIds,
}: {
  title?: string
  errors: Record<string, string>
  fieldIdPrefix: string
  fieldIds?: Record<string, string>
}) {
  const summaryRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    summaryRef.current?.focus()
  }, [])

  if (Object.keys(errors).length === 0) return null

  return (
    <div
      ref={summaryRef}
      className="rounded-lg border border-destructive/25 bg-danger-surface p-3 text-sm"
      role="alert"
      tabIndex={-1}
    >
      <p className="font-medium">{title}</p>
      <ul className="mt-1.5 space-y-1">
        {Object.entries(errors).map(([field, message]) => (
          <li key={field}>
            <a
              className="font-medium text-foreground underline decoration-destructive/70 underline-offset-4"
              href={`#${fieldIds?.[field] ?? `${fieldIdPrefix}-${field}`}`}
            >
              {message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <p id={id} className="text-xs text-destructive">
      {message}
    </p>
  ) : null
}
