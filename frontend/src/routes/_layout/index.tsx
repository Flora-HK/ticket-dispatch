import { createFileRoute, Link } from "@tanstack/react-router"
import { Bell, Ticket } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "概览 - 工单派发系统",
      },
    ],
  }),
})

function Dashboard() {
  const { user: currentUser } = useAuth()

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="truncate text-3xl font-bold tracking-tight">
          工单派发概览
        </h1>
        <p className="text-muted-foreground">
          {currentUser?.full_name || currentUser?.email}，当前角色：
          {currentUser?.roles.join(" / ") || "加载中"}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <Ticket className="size-6 text-primary" />
            <CardTitle>工单中心</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              创建、查看、派发并推进工单处理流程。
            </p>
            <Button asChild className="w-fit">
              <Link to="/tickets">进入工单中心</Link>
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Bell className="size-6 text-primary" />
            <CardTitle>通知中心</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              查看派发给当前接收人的站内通知。
            </p>
            <Button variant="outline" asChild className="w-fit">
              <Link to="/notifications">查看通知</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
