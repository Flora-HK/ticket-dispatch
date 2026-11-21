import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ArrowLeft, ArrowRight, Bell, RefreshCw } from "lucide-react"
import { useState } from "react"

import { NotificationsService, type NotificationType } from "@/client"
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "@/components/shared/AsyncState"
import { DataPager } from "@/components/shared/DataPager"
import { PageHeader } from "@/components/shared/PageHeader"
import { formatDateTime } from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { extractErrorMessage, getApiErrorMeta } from "@/utils"

type NotificationFilters = {
  type?: NotificationType
  from?: string
  to?: string
}

export function NotificationsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filters, setFilters] = useState<NotificationFilters>({})

  const notifications = useInfiniteQuery({
    queryKey: ["notifications", filters],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await NotificationsService.readNotifications({
          query: {
            notification_type: filters.type ?? null,
            created_from: filters.from ? `${filters.from}T00:00:00` : null,
            created_to: filters.to ? `${filters.to}T23:59:59` : null,
            cursor: pageParam,
            limit: 30,
            sort: "created_at:desc",
          },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
  const detail = useQuery({
    queryKey: ["notification", selectedId],
    queryFn: async () =>
      (
        await NotificationsService.readNotificationDetail({
          path: { notification_id: selectedId! },
        })
      ).data,
    enabled: Boolean(selectedId),
  })

  const items = notifications.data?.pages.flatMap((page) => page.items) ?? []
  const errorMeta = notifications.error
    ? getApiErrorMeta(notifications.error)
    : {}

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow="Personal inbox"
        title="通知"
        description="仅展示当前账号接收的站内通知。通知接口只读，不提供标记已读。"
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={notifications.isFetching}
            onClick={() => notifications.refetch()}
          >
            <RefreshCw
              className={notifications.isFetching ? "animate-spin" : undefined}
            />
            刷新
          </Button>
        }
      />

      <Card>
        <CardContent className="grid gap-4 pt-5 md:grid-cols-3">
          <div className="grid gap-2 text-xs font-medium">
            <span>通知类型</span>
            <Select
              value={filters.type ?? "ALL"}
              onValueChange={(value) =>
                setFilters((current) => ({
                  ...current,
                  type:
                    value === "ALL" ? undefined : (value as NotificationType),
                }))
              }
            >
              <SelectTrigger aria-label="通知类型">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">全部类型</SelectItem>
                <SelectItem value="ASSIGNMENT_RECEIVED">收到派发</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>开始日期</span>
            <Input
              aria-label="通知开始日期"
              type="date"
              value={filters.from ?? ""}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  from: event.target.value || undefined,
                }))
              }
            />
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>结束日期</span>
            <Input
              aria-label="通知结束日期"
              type="date"
              value={filters.to ?? ""}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  to: event.target.value || undefined,
                }))
              }
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card
          className={`overflow-hidden py-0 ${selectedId ? "hidden lg:block" : ""}`}
        >
          <CardHeader className="border-b py-4">
            <CardTitle>我的通知</CardTitle>
            <CardDescription>{items.length} 条已加载通知</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {notifications.isLoading ? (
              <LoadingRows rows={6} />
            ) : notifications.isError ? (
              <ErrorState
                message={extractErrorMessage(notifications.error)}
                requestId={errorMeta.requestId}
                onRetry={() => notifications.refetch()}
                className="m-4"
              />
            ) : items.length === 0 ? (
              <EmptyState
                title="当前没有通知"
                description="新的派发通知会出现在这里。"
              />
            ) : (
              <>
                <div className="divide-y">
                  {items.map((notification) => (
                    <button
                      key={notification.id}
                      type="button"
                      className={`flex w-full items-start gap-3 px-4 py-4 text-left hover:bg-muted/45 ${
                        selectedId === notification.id ? "bg-primary/7" : ""
                      }`}
                      onClick={() => setSelectedId(notification.id)}
                    >
                      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                        <Bell className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-start justify-between gap-3">
                          <span className="font-medium">
                            {notification.title}
                          </span>
                          <ArrowRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                        </span>
                        <span className="mt-1 block line-clamp-2 text-sm text-muted-foreground">
                          {notification.message}
                        </span>
                        <span className="mt-1.5 block font-mono text-[11px] text-muted-foreground">
                          {formatDateTime(notification.created_at)}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
                <DataPager
                  hasMore={notifications.hasNextPage}
                  loading={notifications.isFetchingNextPage}
                  onLoadMore={() => notifications.fetchNextPage()}
                />
              </>
            )}
          </CardContent>
        </Card>

        <Card className={selectedId ? "" : "hidden lg:block"}>
          <CardHeader className="border-b">
            <div className="flex items-center gap-2">
              {selectedId ? (
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 lg:hidden"
                  aria-label="返回通知列表"
                  onClick={() => setSelectedId(null)}
                >
                  <ArrowLeft className="size-4" />
                </Button>
              ) : null}
              <div>
                <CardTitle>通知详情</CardTitle>
                <CardDescription>仅本人可查询</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-5">
            {!selectedId ? (
              <p className="text-sm text-muted-foreground">
                从列表选择一条通知查看详情。
              </p>
            ) : detail.isLoading ? (
              <LoadingRows rows={3} className="p-0" />
            ) : detail.isError || !detail.data ? (
              <ErrorState
                title="通知不存在或无权查看"
                message={
                  detail.error
                    ? extractErrorMessage(detail.error)
                    : "通知不存在"
                }
                onRetry={() => detail.refetch()}
              />
            ) : (
              <div className="space-y-5">
                <div>
                  <p className="font-medium">{detail.data.title}</p>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                    {detail.data.message}
                  </p>
                </div>
                <dl className="grid gap-2 rounded-lg bg-muted/50 p-3 text-xs">
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">通知类型</dt>
                    <dd className="font-mono">
                      {detail.data.notification_type}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-muted-foreground">发送时间</dt>
                    <dd className="font-mono">
                      {formatDateTime(detail.data.created_at)}
                    </dd>
                  </div>
                </dl>
                <Button asChild className="w-full">
                  <Link
                    to="/tickets/$ticketId"
                    params={{ ticketId: detail.data.ticket_id }}
                  >
                    查看关联工单
                    <ArrowRight />
                  </Link>
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
