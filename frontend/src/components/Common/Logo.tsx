import { Link } from "@tanstack/react-router"
import { Route } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <span
          className={cn(
            "flex items-center gap-2.5 group-data-[collapsible=icon]:hidden",
            className,
          )}
        >
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Route className="size-4.5" />
          </span>
          <span className="leading-none">
            <span className="block text-sm font-semibold tracking-tight">
              Dispatch Desk
            </span>
            <span className="mt-1 block text-[10px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
              工单派发系统
            </span>
          </span>
        </span>
        <span
          className={cn(
            "hidden size-8 place-items-center rounded-lg bg-primary text-primary-foreground group-data-[collapsible=icon]:grid",
            className,
          )}
        >
          <Route className="size-4.5" />
        </span>
      </>
    ) : (
      <span className={cn("inline-flex items-center gap-3", className)}>
        <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground">
          <Route className="size-5" />
        </span>
        {variant === "full" ? (
          <span className="leading-none">
            <span className="block text-base font-semibold tracking-tight">
              Dispatch Desk
            </span>
            <span className="mt-1 block text-[10px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
              工单派发系统
            </span>
          </span>
        ) : null}
      </span>
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
