import { Link, useRouterState } from "@tanstack/react-router"
import { Bell, ChevronRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SidebarTrigger } from "@/components/ui/sidebar"

const routeTitles: Array<{ match: RegExp; title: string; parent?: string }> = [
  { match: /^\/tickets\/[^/]+$/, title: "工单详情", parent: "工单" },
  { match: /^\/tickets$/, title: "工单" },
  { match: /^\/dispatch$/, title: "派发工作台" },
  { match: /^\/notifications$/, title: "通知" },
  { match: /^\/admin\/users$/, title: "用户与角色", parent: "管理" },
  { match: /^\/admin\/teams$/, title: "Team 与成员", parent: "管理" },
  { match: /^\/admin\/audit$/, title: "审计查询", parent: "管理" },
  { match: /^\/$/, title: "总览" },
]

function pageTitle(pathname: string): {
  title: string
  parent?: string
} {
  return (
    routeTitles.find((route) => route.match.test(pathname)) ?? {
      title: "Dispatch Desk",
    }
  )
}

export function AppTopbar() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const current = pageTitle(pathname)

  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-background/95 px-3 backdrop-blur-sm md:px-5">
      <div className="flex min-w-0 items-center gap-2">
        <SidebarTrigger
          aria-label="打开导航"
          className="-ml-1 text-muted-foreground"
        />
        <div className="flex min-w-0 items-center gap-1.5 text-sm">
          {current.parent ? (
            <>
              <span className="hidden text-muted-foreground sm:inline">
                {current.parent}
              </span>
              <ChevronRight className="hidden size-3.5 text-muted-foreground sm:block" />
            </>
          ) : null}
          <span className="truncate font-medium">{current.title}</span>
        </div>
      </div>
      <Button variant="ghost" size="icon" asChild>
        <Link to="/notifications" aria-label="打开通知">
          <Bell className="size-4.5" />
        </Link>
      </Button>
    </header>
  )
}
