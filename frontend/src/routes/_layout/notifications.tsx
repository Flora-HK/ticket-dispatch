import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Bell, RefreshCw } from "lucide-react"
import { useState } from "react"

import { NotificationsService } from "@/client"
import { formatDateTime } from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/notifications")({
  component: NotificationsPage,
  head: () => ({ meta: [{ title: "通知中心 - 工单派发系统" }] }),
})

function NotificationsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const notifications = useQuery({
    queryKey: ["notifications"],
    queryFn: async () =>
      (
        await NotificationsService.readNotifications({
          query: { limit: 100 },
        })
      ).data,
  })
  const detail = useQuery({
    queryKey: ["notification", selectedId],
    queryFn: async () =>
      (
        await NotificationsService.readNotificationDetail({
          path: { notification_id: selectedId! },
        })
      ).data,
    enabled: selectedId !== null,
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">通知中心</h1>
          <p className="text-muted-foreground">仅展示当前账号接收的通知</p>
        </div>
        <Button
          variant="outline"
          onClick={() => {
            setSelectedId(null)
            notifications.refetch()
          }}
        >
          <RefreshCw
            className={notifications.isFetching ? "animate-spin" : ""}
          />
          刷新
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="py-0">
          <CardHeader className="border-b py-5">
            <CardTitle>
              {notifications.data
                ? `${notifications.data.items.length} 条通知`
                : "通知列表"}
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y p-0">
            {notifications.isLoading ? (
              <p className="p-8 text-center text-muted-foreground">
                正在加载通知…
              </p>
            ) : notifications.isError ? (
              <p className="p-8 text-center text-destructive">
                {extractErrorMessage(notifications.error)}
              </p>
            ) : notifications.data?.items.length === 0 ? (
              <div className="flex flex-col items-center gap-3 p-12 text-center">
                <Bell className="size-8 text-muted-foreground" />
                <p className="text-muted-foreground">当前没有通知。</p>
              </div>
            ) : (
              notifications.data?.items.map((notification) => (
                <button
                  key={notification.id}
                  type="button"
                  className="flex w-full flex-col gap-1 p-5 text-left hover:bg-muted/40"
                  onClick={() => setSelectedId(notification.id)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{notification.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(notification.created_at)}
                    </span>
                  </div>
                  <span className="text-sm text-muted-foreground">
                    {notification.message}
                  </span>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>通知详情</CardTitle>
            <CardDescription>仅本人可查询，不提供已读写入</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 text-sm">
            {!selectedId ? (
              <p className="text-muted-foreground">
                从左侧选择一条通知查看详情。
              </p>
            ) : detail.isLoading ? (
              <p className="text-muted-foreground">正在加载详情…</p>
            ) : detail.isError || !detail.data ? (
              <p className="text-destructive">
                {detail.error
                  ? extractErrorMessage(detail.error)
                  : "通知不存在"}
              </p>
            ) : (
              <>
                <div>
                  <p className="font-medium">{detail.data.title}</p>
                  <p className="mt-1 text-muted-foreground">
                    {detail.data.message}
                  </p>
                </div>
                <dl className="grid gap-2 text-xs text-muted-foreground">
                  <div>
                    <dt>通知类型</dt>
                    <dd>{detail.data.notification_type}</dd>
                  </div>
                  <div>
                    <dt>发送时间</dt>
                    <dd>{formatDateTime(detail.data.created_at)}</dd>
                  </div>
                </dl>
                <Button variant="outline" asChild>
                  <Link
                    to="/tickets/$ticketId"
                    params={{ ticketId: detail.data.ticket_id }}
                  >
                    查看关联工单
                  </Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
