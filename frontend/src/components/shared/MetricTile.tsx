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
  return (
    <div className="rounded-xl border bg-card px-4 py-4 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className="mt-2 font-mono text-2xl font-semibold tracking-tight tabular-nums">
            {value}
          </p>
          {detail ? (
            <p className="mt-1 text-[11px] text-muted-foreground">{detail}</p>
          ) : null}
        </div>
        <span
          className={cn(
            "grid size-9 place-items-center rounded-lg",
            tone === "default" && "bg-primary/10 text-primary",
            tone === "warning" &&
              "bg-amber-500/10 text-amber-700 dark:text-amber-300",
            tone === "danger" && "bg-destructive/10 text-destructive",
            tone === "success" &&
              "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
          )}
        >
          <Icon className="size-4" />
        </span>
      </div>
    </div>
  )
}
