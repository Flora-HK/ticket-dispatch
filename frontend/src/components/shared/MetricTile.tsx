import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export function MetricTile({
  label,
  value,
  detail,
  icon: Icon,
  tone = "default",
}: {
  label: string
  value: string | number
  detail?: string
  icon: LucideIcon
  tone?: "default" | "warning" | "danger" | "success"
}) {
  const resolvedTone =
    Number(value) === 0 && tone !== "default" ? "neutral" : tone

  return (
    <div
      className="rounded-lg border bg-card px-4 py-3.5 shadow-none"
      data-tone={resolvedTone}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-meta font-medium text-muted-foreground">{label}</p>
          <p className="mt-1.5 font-mono text-[1.375rem] font-semibold tracking-tight tabular-nums">
            {value}
          </p>
          {detail ? (
            <p className="mt-1 text-meta text-muted-foreground">{detail}</p>
          ) : null}
        </div>
        <span
          className={cn(
            "grid size-8 place-items-center rounded-md",
            (resolvedTone === "default" || resolvedTone === "neutral") &&
              "bg-muted text-muted-foreground",
            resolvedTone === "warning" &&
              "bg-amber-500/10 text-amber-700 dark:text-amber-300",
            resolvedTone === "danger" && "bg-destructive/10 text-destructive",
            resolvedTone === "success" &&
              "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
          )}
        >
          <Icon className="size-4" />
        </span>
      </div>
    </div>
  )
}
