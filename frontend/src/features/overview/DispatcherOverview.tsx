import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  AlertTriangle,
  ArrowRight,
  ClipboardClock,
  Clock3,
  RefreshCw,
  TicketCheck,
  UsersRound,
} from "lucide-react"
import { useMemo } from "react"

import {
  AssignmentsService,
  type DispatchCandidateListResponse,
  TicketsService,
} from "@/client"
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "@/components/shared/AsyncState"
import { MetricTile } from "@/components/shared/MetricTile"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatDateTime } from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import { extractErrorMessage, getApiErrorMeta } from "@/utils"

import {
  buildOverviewSnapshot,
  collectTicketPages,
  formatWaitDuration,
  isPendingOverdue,
  type OverviewTicket,
  summarizeWorkload,
  workloadBarWidth,
} from "./overview-data"

type OverviewQueryData = {
  tickets: OverviewTicket[]
  candidateGroups: DispatchCandidateListResponse[]
  partial: boolean
}

async function readOverviewTickets() {
  return collectTicketPages(
    async (cursor) =>
      (
        await TicketsService.readTickets({
          query: {
            cursor: cursor ?? null,
            limit: 100,
            sort: "updated_at:desc",
          },
        })
      ).data,
    { maxItems: 500 },
  )
}

async function readCandidatePreview(
  tickets: OverviewTicket[],
  canDispatch: boolean,
) {
  if (!canDispatch) return []

  const seenTeams = new Set<string>()
  const ticketIds = tickets
    .filter(
      (ticket) =>
        ticket.status === "PENDING_ASSIGNMENT" &&
        !seenTeams.has(ticket.team_id) &&
        seenTeams.add(ticket.team_id),
    )
    .slice(0, 12)
    .map((ticket) => ticket.id)

  const settled = await Promise.allSettled(
    ticketIds.map(async (ticketId) => {
      const response = await AssignmentsService.getDispatchCandidates({
        path: { ticket_id: ticketId },
      })
      return response.data
    }),
  )

  return settled.flatMap((result) =>
    result.status === "fulfilled" ? [result.value] : [],
  )
}

export function DispatcherOverview() {
  const { user } = useAuth()
  const canDispatch =
    user?.roles.includes("DISPATCHER") || user?.roles.includes("ADMIN")
  const overview = useQuery({
    queryKey: ["overview", "snapshot", user?.id ?? "anonymous"],
    queryFn: async (): Promise<OverviewQueryData> => {
      const result = await readOverviewTickets()
      const pendingTickets = result.items
        .filter((ticket) => ticket.status === "PENDING_ASSIGNMENT")
        .sort((left, right) => left.updated_at.localeCompare(right.updated_at))
      const candidateGroups = await readCandidatePreview(
        pendingTickets,
        Boolean(canDispatch),
      )
      return {
        tickets: result.items,
        candidateGroups,
        partial: result.partial,
      }
    },
    enabled: Boolean(user),
  })

  const snapshot = useMemo(() => {
    if (!overview.data) return null
    return buildOverviewSnapshot(
      overview.data.tickets,
      overview.data.candidateGroups.map((group) =>
        group.items.map((candidate) => ({
          handler_id: candidate.handler_id,
          open_ticket_count: candidate.open_ticket_count,
        })),
      ),
      new Date(),
      overview.data.partial,
    )
  }, [overview.data])

  const workload = useMemo(() => {
    const byHandler = new Map<
      string,
      { name: string; load: number; lastAssignedAt: string | null }
    >()
    for (const group of overview.data?.candidateGroups ?? []) {
      for (const candidate of group.items) {
        const existing = byHandler.get(candidate.handler_id)
        const next = {
          name:
            candidate.handler.full_name ||
            candidate.handler.email ||
            candidate.handler_id.slice(0, 8),
          load: candidate.open_ticket_count,
          lastAssignedAt: candidate.last_assigned_at,
        }
        if (!existing || next.load > existing.load) {
          byHandler.set(candidate.handler_id, next)
        }
      }
    }
    return [...byHandler.values()].sort((left, right) => right.load - left.load)
  }, [overview.data])

  const errorMeta = overview.error ? getApiErrorMeta(overview.error) : {}
  const now = new Date()
  const workloadSummary = summarizeWorkload(workload.map((item) => item.load))
  const maxLoad = Math.max(1, workloadSummary.max)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={canDispatch ? "派发总览" : "工作总览"}
        description={
          canDispatch
            ? "从待派发队列开始工作，同时掌握团队负载与需要介入的异常。"
            : "查看当前账号可见的工单进度与待处理事项。"
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={overview.isFetching}
            onClick={() => overview.refetch()}
          >
            <RefreshCw
              className={overview.isFetching ? "animate-spin" : undefined}
            />
            刷新
          </Button>
        }
      />

      {overview.isLoading ? (
        <Card>
          <LoadingRows rows={7} />
        </Card>
      ) : overview.isError ? (
        <ErrorState
          message={extractErrorMessage(overview.error)}
          requestId={errorMeta.requestId}
          onRetry={() => overview.refetch()}
        />
      ) : snapshot ? (
        <>
          {snapshot.partial ? (
            <p className="rounded-lg border border-amber-500/25 bg-amber-500/8 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
              指标基于最近 500 张可见工单，当前数据未覆盖全部历史记录。
            </p>
          ) : null}

          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <MetricTile
              label="待派发"
              value={snapshot.counts.PENDING_ASSIGNMENT}
              detail="等待分配合格处理人"
              icon={ClipboardClock}
              tone="warning"
            />
            <MetricTile
              label="处理中"
              value={snapshot.counts.IN_PROGRESS}
              detail="处理人已接受"
              icon={Clock3}
            />
            <MetricTile
              label="待确认"
              value={snapshot.counts.PENDING_CONFIRMATION}
              detail="等待提交人确认完成"
              icon={TicketCheck}
              tone="success"
            />
            <MetricTile
              label="异常提醒"
              value={snapshot.exceptions.reduce(
                (total, item) => total + item.count,
                0,
              )}
              detail="超时或负载失衡"
              icon={AlertTriangle}
              tone="danger"
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.8fr)]">
            <Card className="overflow-hidden py-0" data-testid="priority-queue">
              <CardHeader className="border-b py-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      优先队列
                      <StatusBadge kind="ticket" value="PENDING_ASSIGNMENT" />
                    </CardTitle>
                    <CardDescription>
                      服务端可见范围内等待派发的工单
                    </CardDescription>
                  </div>
                  {canDispatch ? (
                    <Button variant="ghost" size="sm" asChild>
                      <Link to="/dispatch">
                        工作台
                        <ArrowRight />
                      </Link>
                    </Button>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {snapshot.pending.length === 0 ? (
                  <EmptyState
                    title="待派发队列已清空"
                    description="当前没有需要 Dispatcher 介入的待派发工单。"
                  />
                ) : (
                  <>
                    <div className="hidden md:block">
                      <Table className="table-fixed">
                        <TableHeader>
                          <TableRow>
                            <TableHead>工单</TableHead>
                            <TableHead className="w-28">Team</TableHead>
                            <TableHead className="w-52">等待</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {snapshot.pending.slice(0, 7).map((ticket) => (
                            <TableRow
                              key={ticket.id}
                              className="relative cursor-pointer focus-within:bg-muted/50"
                            >
                              <TableCell className="max-w-sm">
                                <Link
                                  to="/tickets/$ticketId"
                                  params={{ ticketId: ticket.id }}
                                  aria-label={`打开工单 ${ticket.title}`}
                                  className="absolute inset-0 z-10 rounded-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                                />
                                <div className="flex items-center gap-2">
                                  <span
                                    className="size-1.5 shrink-0 rounded-full bg-status-pending"
                                    aria-hidden="true"
                                  />
                                  <span className="truncate font-medium">
                                    {ticket.title}
                                  </span>
                                </div>
                                <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                                  {ticket.submitter.full_name ||
                                    ticket.submitter.email}
                                </p>
                              </TableCell>
                              <TableCell className="truncate">
                                {ticket.team.name}
                              </TableCell>
                              <TableCell>
                                <QueueWait
                                  updatedAt={ticket.updated_at}
                                  now={now}
                                />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <div className="divide-y md:hidden">
                      {snapshot.pending.slice(0, 5).map((ticket) => (
                        <Link
                          key={ticket.id}
                          to="/tickets/$ticketId"
                          params={{ ticketId: ticket.id }}
                          className="block px-4 py-3"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <p className="line-clamp-2 text-sm font-medium">
                              {ticket.title}
                            </p>
                            <span
                              className="mt-1.5 size-1.5 shrink-0 rounded-full bg-status-pending"
                              aria-hidden="true"
                            />
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {ticket.team.name} ·{" "}
                            {ticket.submitter.full_name ||
                              ticket.submitter.email}
                          </p>
                          <div className="mt-2">
                            <QueueWait
                              updatedAt={ticket.updated_at}
                              now={now}
                            />
                          </div>
                        </Link>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            <div className="flex flex-col gap-5">
              <Card data-testid="workload-panel">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2">
                    <UsersRound className="size-4 text-primary" />
                    团队负载
                  </CardTitle>
                  <CardDescription>
                    候选人接口返回的当前活动工单负载
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {workload.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      当前没有可比较的候选处理人。
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <div className="grid grid-cols-3 gap-2 border-b pb-3 text-xs">
                        <WorkloadDatum
                          label="最高"
                          value={workloadSummary.max}
                        />
                        <WorkloadDatum
                          label="最低"
                          value={workloadSummary.min}
                        />
                        <WorkloadDatum
                          label="差值"
                          value={workloadSummary.delta}
                          warning={workloadSummary.skewed}
                        />
                      </div>
                      {workload.slice(0, 6).map((item) => (
                        <div key={item.name}>
                          <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                            <span className="truncate font-medium">
                              {item.name}
                            </span>
                            <span className="font-mono tabular-nums text-muted-foreground">
                              {item.load}
                            </span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn(
                                "h-full rounded-full",
                                workloadSummary.skewed &&
                                  item.load === workloadSummary.max
                                  ? "bg-amber-500"
                                  : "bg-primary",
                              )}
                              style={{
                                width: `${workloadBarWidth(item.load, maxLoad)}%`,
                              }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card data-testid="exception-panel">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2">
                    <AlertTriangle className="size-4 text-amber-600 dark:text-amber-300" />
                    需要关注
                  </CardTitle>
                  <CardDescription>
                    由当前接口数据和明确时间规则推导
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {snapshot.exceptions.length === 0 ? (
                    <div className="rounded-lg bg-muted/55 px-3 py-4 text-sm text-muted-foreground">
                      当前没有触发异常规则。
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {snapshot.exceptions.map((item) => (
                        <Link
                          key={item.code}
                          to={
                            item.code === "WORKLOAD_SKEW"
                              ? "/dispatch"
                              : "/tickets"
                          }
                          search={
                            item.code === "PENDING_OVER_24H"
                              ? {
                                  status: "PENDING_ASSIGNMENT",
                                  sort: "updated_at:asc",
                                }
                              : item.code === "CONFIRMATION_OVER_48H"
                                ? {
                                    status: "PENDING_CONFIRMATION",
                                    sort: "updated_at:asc",
                                  }
                                : undefined
                          }
                          className="group flex min-h-11 items-center justify-between gap-3 rounded-lg border border-amber-500/20 bg-amber-500/6 px-3 py-2.5 transition-colors hover:bg-amber-500/10 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                        >
                          <span className="text-sm">{item.label}</span>
                          <span className="flex items-center gap-2">
                            <span className="font-mono text-sm font-semibold tabular-nums">
                              {item.count}
                            </span>
                            <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                          </span>
                        </Link>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

function QueueWait({ updatedAt, now }: { updatedAt: string; now: Date }) {
  const overdue = isPendingOverdue(updatedAt, now)
  return (
    <div
      className={cn(
        "whitespace-normal text-xs",
        overdue ? "font-medium text-amber-800 dark:text-amber-200" : "",
      )}
      data-testid="queue-wait-time"
    >
      <time className="whitespace-nowrap" dateTime={updatedAt}>
        {formatWaitDuration(updatedAt, now)}
      </time>
      {overdue ? (
        <span className="mt-0.5 block whitespace-nowrap text-[11px]">
          已超过 24 小时
        </span>
      ) : null}
      <span className="mt-0.5 block whitespace-nowrap text-[11px] text-muted-foreground">
        更新于 {formatDateTime(updatedAt)}
      </span>
    </div>
  )
}

function WorkloadDatum({
  label,
  value,
  warning = false,
}: {
  label: string
  value: number
  warning?: boolean
}) {
  return (
    <div>
      <p className="text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 font-mono font-semibold tabular-nums",
          warning ? "text-amber-700 dark:text-amber-300" : "",
        )}
      >
        {value}
      </p>
    </div>
  )
}
