import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import {
  ArrowRight,
  Bot,
  Check,
  RefreshCw,
  Scale,
  UserRound,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import {
  AssignmentsService,
  type DispatchResponse,
  type TicketDetailPublic,
  TicketsService,
} from "@/client"
import {
  EmptyState,
  ErrorState,
  InlineLoading,
  LoadingRows,
} from "@/components/shared/AsyncState"
import { ConflictBanner } from "@/components/shared/ConflictBanner"
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
import { Input } from "@/components/ui/input"
import {
  createSubmissionKey,
  hasTicketAction,
} from "@/features/actions/ticket-actions"
import { cn } from "@/lib/utils"
import { extractErrorMessage, isConflictError } from "@/utils"

type DispatchMode = "MANUAL" | "AUTO"

export function DispatchWorkbench({
  initialTicketId,
}: {
  initialTicketId?: string
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | undefined>(
    initialTicketId,
  )
  const [selectedHandlerId, setSelectedHandlerId] = useState("")
  const [reason, setReason] = useState("")
  const [mode, setMode] = useState<DispatchMode>("MANUAL")
  const [explanation, setExplanation] = useState<DispatchResponse | null>(null)
  const [conflict, setConflict] = useState<{
    message: string
    refreshed: boolean
  } | null>(null)

  const queue = useInfiniteQuery({
    queryKey: ["dispatch-queue"],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await TicketsService.readTickets({
          query: {
            status: "PENDING_ASSIGNMENT",
            cursor: pageParam,
            limit: 30,
            sort: "updated_at:asc",
          },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
  const queueItems = queue.data?.pages.flatMap((page) => page.items) ?? []

  useEffect(() => {
    if (!selectedId && queueItems[0]) {
      setSelectedId(queueItems[0].id)
    }
  }, [queueItems, selectedId])

  const ticket = useQuery({
    queryKey: ["ticket", selectedId],
    queryFn: async () =>
      (
        await TicketsService.readTicket({
          path: { ticket_id: selectedId! },
        })
      ).data,
    enabled: Boolean(selectedId),
  })
  const candidates = useQuery({
    queryKey: ["dispatch-candidates", selectedId],
    queryFn: async () =>
      (
        await AssignmentsService.getDispatchCandidates({
          path: { ticket_id: selectedId! },
        })
      ).data,
    enabled: Boolean(ticket.data && hasTicketAction(ticket.data, "DISPATCH")),
  })

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["dispatch-queue"] }),
      queryClient.invalidateQueries({ queryKey: ["tickets"] }),
      queryClient.invalidateQueries({ queryKey: ["overview"] }),
      queryClient.invalidateQueries({ queryKey: ["ticket", selectedId] }),
      queryClient.invalidateQueries({
        queryKey: ["dispatch-candidates", selectedId],
      }),
    ])
  }

  const dispatch = useMutation({
    mutationFn: async ({
      detail,
      dispatchMode,
    }: {
      detail: TicketDetailPublic
      dispatchMode: DispatchMode
    }) => {
      if (dispatchMode === "MANUAL" && !selectedHandlerId) {
        throw new Error("请选择处理人")
      }
      const expected = detail.active_assignment
        ? {
            reason: reason.trim() || null,
            expected_assignment_id: detail.active_assignment.id,
            expected_assignment_version: detail.active_assignment.version,
          }
        : {}
      const body =
        dispatchMode === "MANUAL"
          ? {
              mode: "MANUAL" as const,
              handler_id: selectedHandlerId,
              expected_ticket_version: detail.version,
              ...expected,
            }
          : {
              mode: "AUTO" as const,
              strategy: "LEAST_OPEN_TICKET" as const,
              expected_ticket_version: detail.version,
              ...expected,
            }
      return (
        await AssignmentsService.dispatchTicket({
          path: { ticket_id: detail.id },
          body,
          headers: { "Idempotency-Key": createSubmissionKey() },
        })
      ).data
    },
    onSuccess: async (response) => {
      setExplanation(response)
      setConflict(null)
      setReason("")
      setSelectedHandlerId("")
      await refreshAll()
    },
    onError: async (error) => {
      if (isConflictError(error)) {
        setConflict({ message: extractErrorMessage(error), refreshed: false })
        await refreshAll()
        setConflict((current) =>
          current ? { ...current, refreshed: true } : null,
        )
        return
      }
      setConflict({ message: extractErrorMessage(error), refreshed: true })
    },
  })

  const selectedTicket = ticket.data
  const canDispatchSelected = selectedTicket
    ? hasTicketAction(selectedTicket, "DISPATCH")
    : false
  const needReason = Boolean(selectedTicket?.active_assignment)
  const canSubmit =
    Boolean(selectedTicket) &&
    canDispatchSelected &&
    !dispatch.isPending &&
    (mode === "AUTO" || Boolean(selectedHandlerId)) &&
    (!needReason || Boolean(reason.trim()))

  const selectedCandidate = useMemo(
    () =>
      candidates.data?.items.find(
        (candidate) => candidate.handler_id === selectedHandlerId,
      ),
    [candidates.data, selectedHandlerId],
  )

  const chooseTicket = (ticketId: string) => {
    setSelectedId(ticketId)
    setSelectedHandlerId("")
    setReason("")
    setExplanation(null)
    setConflict(null)
    void navigate({
      to: "/dispatch",
      search: { ticket: ticketId },
      replace: true,
    })
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="派发工作台"
        description="比较服务端候选排名与实时负载，再选择人工指定或最低负载自动派发。"
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={queue.isFetching}
            onClick={() => {
              void queue.refetch()
              void candidates.refetch()
            }}
          >
            <RefreshCw
              className={queue.isFetching ? "animate-spin" : undefined}
            />
            刷新
          </Button>
        }
      />

      {conflict ? (
        <ConflictBanner
          message={conflict.message}
          refreshed={conflict.refreshed}
          onDismiss={() => setConflict(null)}
        />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_340px] xl:items-start">
        <Card className="overflow-hidden py-0">
          <CardHeader className="border-b py-4">
            <CardTitle>待派发队列</CardTitle>
            <CardDescription>{queueItems.length} 条可见待办</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[360px] overflow-auto p-0 xl:max-h-[720px]">
            {queue.isLoading ? (
              <LoadingRows rows={6} />
            ) : queue.isError ? (
              <ErrorState
                message={extractErrorMessage(queue.error)}
                onRetry={() => queue.refetch()}
                className="m-3"
              />
            ) : queueItems.length === 0 ? (
              <EmptyState
                title="没有待派发工单"
                description="新的待派发工单会出现在这里。"
              />
            ) : (
              <div className="divide-y">
                {queueItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => chooseTicket(item.id)}
                    className={cn(
                      "w-full px-4 py-3 text-left transition-colors hover:bg-muted/60",
                      selectedId === item.id && "bg-primary/7",
                    )}
                    aria-pressed={selectedId === item.id}
                  >
                    <p className="line-clamp-2 text-sm font-medium">
                      {item.title}
                    </p>
                    <div className="mt-1.5 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                      <span className="truncate">{item.team.name}</span>
                      <span className="shrink-0 font-mono">
                        {formatDateTime(item.updated_at)}
                      </span>
                    </div>
                  </button>
                ))}
                {queue.hasNextPage ? (
                  <div className="p-3">
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      disabled={queue.isFetchingNextPage}
                      onClick={() => queue.fetchNextPage()}
                    >
                      {queue.isFetchingNextPage ? "正在加载…" : "加载更多"}
                    </Button>
                  </div>
                ) : null}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          {!selectedId ? (
            <EmptyState
              title="选择一张工单"
              description="从左列选择待派发工单查看详情。"
            />
          ) : ticket.isLoading ? (
            <LoadingRows rows={9} />
          ) : ticket.isError || !selectedTicket ? (
            <ErrorState
              message={
                ticket.error
                  ? extractErrorMessage(ticket.error)
                  : "工单不存在或无权查看"
              }
              onRetry={() => ticket.refetch()}
              className="m-4"
            />
          ) : (
            <>
              <CardHeader className="border-b">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge kind="ticket" value={selectedTicket.status} />
                  <span className="font-mono text-xs text-muted-foreground">
                    v{selectedTicket.version}
                  </span>
                </div>
                <CardTitle className="text-xl leading-tight">
                  {selectedTicket.title}
                </CardTitle>
                <CardDescription>
                  {selectedTicket.team.name} ·{" "}
                  {selectedTicket.submitter.full_name ||
                    selectedTicket.submitter.email}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5 pt-5">
                <section>
                  <p className="mb-2 text-xs font-semibold tracking-[0.1em] text-muted-foreground uppercase">
                    工单描述
                  </p>
                  <p className="whitespace-pre-wrap text-sm leading-6">
                    {selectedTicket.description}
                  </p>
                </section>
                <dl className="grid gap-3 rounded-lg bg-muted/55 p-4 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs text-muted-foreground">创建时间</dt>
                    <dd className="mt-0.5 font-mono text-xs">
                      {formatDateTime(selectedTicket.created_at)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">更新时间</dt>
                    <dd className="mt-0.5 font-mono text-xs">
                      {formatDateTime(selectedTicket.updated_at)}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </>
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader className="border-b py-4">
            <CardTitle>派发决策</CardTitle>
            <CardDescription>
              预览不减损服务端锁内重算与最终校验
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
              <button
                type="button"
                disabled={!canDispatchSelected}
                className={cn(
                  "rounded-md px-3 py-2 text-sm font-medium max-md:min-h-11",
                  mode === "MANUAL"
                    ? "bg-background shadow-xs"
                    : "text-muted-foreground",
                )}
                onClick={() => setMode("MANUAL")}
              >
                人工派发
              </button>
              <button
                type="button"
                disabled={!canDispatchSelected}
                className={cn(
                  "rounded-md px-3 py-2 text-sm font-medium max-md:min-h-11",
                  mode === "AUTO"
                    ? "bg-background shadow-xs"
                    : "text-muted-foreground",
                )}
                onClick={() => setMode("AUTO")}
              >
                自动派发
              </button>
            </div>

            {!canDispatchSelected ? (
              <div className="rounded-lg border border-amber-500/25 bg-amber-500/8 p-3 text-sm">
                当前工单或账号不允许执行派发，请刷新后检查最新权限与状态。
              </div>
            ) : candidates.isLoading ? (
              <InlineLoading label="正在读取候选处理人" />
            ) : candidates.isError ? (
              <ErrorState
                message={extractErrorMessage(candidates.error)}
                onRetry={() => candidates.refetch()}
              />
            ) : candidates.data?.items.length === 0 ? (
              <div className="rounded-lg border border-amber-500/25 bg-amber-500/8 p-3 text-sm">
                当前 Team 没有合格处理人。
              </div>
            ) : (
              <div className="space-y-2" data-testid="candidate-ranking">
                {candidates.data?.items.map((candidate) => {
                  const selected = candidate.handler_id === selectedHandlerId
                  return (
                    <button
                      key={candidate.handler_id}
                      type="button"
                      disabled={mode !== "MANUAL"}
                      onClick={() => setSelectedHandlerId(candidate.handler_id)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                        selected
                          ? "border-primary bg-primary/7"
                          : "hover:bg-muted/50",
                        mode !== "MANUAL" && "opacity-65",
                      )}
                      aria-pressed={selected}
                    >
                      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted">
                        {selected ? (
                          <Check className="size-4 text-primary" />
                        ) : (
                          <UserRound className="size-4 text-muted-foreground" />
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {candidate.handler.full_name ||
                            candidate.handler.email}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-muted-foreground">
                          #{candidate.rank} · 活动负载{" "}
                          {candidate.open_ticket_count}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}

            {needReason ? (
              <div className="grid gap-2">
                <label
                  htmlFor="dispatch-reason"
                  className="text-xs font-medium"
                >
                  重新派发原因
                </label>
                <Input
                  id="dispatch-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="说明为什么更换当前处理人"
                />
              </div>
            ) : null}

            {mode === "AUTO" ? (
              <div className="flex gap-3 rounded-lg bg-muted/55 p-3 text-sm">
                <Scale className="mt-0.5 size-4 shrink-0 text-primary" />
                <p className="text-muted-foreground">
                  使用最低活动负载策略，负载相同则依次比较最近派发时间和 Handler
                  UUID。
                </p>
              </div>
            ) : null}

            <Button
              className="w-full"
              disabled={!canSubmit}
              onClick={() => {
                if (selectedTicket) {
                  dispatch.mutate({
                    detail: selectedTicket,
                    dispatchMode: mode,
                  })
                }
              }}
            >
              {mode === "MANUAL" ? <ArrowRight /> : <Bot />}
              {dispatch.isPending
                ? "正在提交…"
                : mode === "MANUAL"
                  ? "确认人工派发"
                  : "按最低负载自动派发"}
            </Button>

            {mode === "MANUAL" && selectedCandidate ? (
              <p className="text-center text-xs text-muted-foreground">
                将派发给{" "}
                {selectedCandidate.handler.full_name ||
                  selectedCandidate.handler.email}
              </p>
            ) : null}

            {explanation ? (
              <div
                className="rounded-lg border border-emerald-500/25 bg-emerald-500/8 p-3 text-sm"
                data-testid="dispatch-explanation"
                aria-live="polite"
              >
                <p className="font-medium">派发完成</p>
                <p className="mt-1 text-muted-foreground">
                  从 {explanation.explanation.candidate_count} 名候选中选择，
                  选中时负载为{" "}
                  {explanation.explanation.selected_open_ticket_count}。
                </p>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
