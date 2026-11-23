import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Bot,
  Clock3,
  History,
  MessageSquareText,
  Pencil,
  Send,
  UserRound,
} from "lucide-react"
import { useState } from "react"

import {
  AssignmentsService,
  CommentsService,
  type TicketAction,
  type TicketDetailPublic,
  TicketsService,
} from "@/client"
import {
  ActionError,
  FieldError,
  FormErrorSummary,
} from "@/components/shared/ActionError"
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "@/components/shared/AsyncState"
import {
  ConflictBanner,
  type ConflictSnapshot,
} from "@/components/shared/ConflictBanner"
import { DataPager } from "@/components/shared/DataPager"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
import {
  formatDateTime,
  ticketStatusLabels,
} from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  getPrimaryTicketAction,
  hasTicketAction,
} from "@/features/actions/ticket-actions"
import {
  extractErrorMessage,
  getApiErrorCode,
  getApiErrorFields,
  getApiErrorMeta,
  isConflictError,
} from "@/utils"

type DialogAction = "REJECT" | "COMPLETE" | "CLOSE" | "REOPEN" | "EDIT"
type ConflictState = {
  message: string
  code?: string
  requestId?: string
  refreshed: boolean
  before?: ConflictSnapshot
  after?: ConflictSnapshot
}
type ActionErrorState = {
  message: string
  requestId?: string
  fields: Record<string, string>
}

const actionCopy: Record<
  Exclude<DialogAction, "EDIT">,
  {
    title: string
    description: string
    placeholder: string
    success: string
    submit: string
  }
> = {
  REJECT: {
    title: "拒绝派发",
    description: "说明无法处理的原因。提交后工单会回到待派发。",
    placeholder: "例如：当前处理人缺少所需权限",
    success: "已拒绝派发",
    submit: "确认拒绝",
  },
  COMPLETE: {
    title: "完成处理",
    description: "请说明处理结果，提交后等待工单提交人确认。",
    placeholder: "填写处理过程与结果",
    success: "处理已完成",
    submit: "提交完成结果",
  },
  CLOSE: {
    title: "关闭工单",
    description: "确认问题已经解决。解决说明可选填。",
    placeholder: "可选：填写确认或解决说明",
    success: "工单已关闭",
    submit: "确认关闭",
  },
  REOPEN: {
    title: "重新打开工单",
    description: "说明问题为何仍需继续处理。",
    placeholder: "填写重新打开的原因",
    success: "工单已重新打开",
    submit: "确认重新打开",
  },
}

export function TicketDetailPage({ ticketId }: { ticketId: string }) {
  const queryClient = useQueryClient()
  const [dialogAction, setDialogAction] = useState<DialogAction | null>(null)
  const [dialogNote, setDialogNote] = useState("")
  const [editTitle, setEditTitle] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [commentBody, setCommentBody] = useState("")
  const [conflict, setConflict] = useState<ConflictState | null>(null)
  const [actionError, setActionError] = useState<ActionErrorState | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)

  const ticket = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: async () =>
      (await TicketsService.readTicket({ path: { ticket_id: ticketId } })).data,
  })
  const comments = useInfiniteQuery({
    queryKey: ["comments", ticketId],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await CommentsService.readComments({
          path: { ticket_id: ticketId },
          query: { cursor: pageParam, limit: 50 },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
  const timeline = useInfiniteQuery({
    queryKey: ["timeline", ticketId],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await TicketsService.readTimeline({
          path: { ticket_id: ticketId },
          query: { cursor: pageParam, limit: 50 },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
  const history = useInfiniteQuery({
    queryKey: ["assignment-history", ticketId],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await AssignmentsService.getAssignmentHistory({
          path: { ticket_id: ticketId },
          query: { cursor: pageParam, limit: 20 },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(ticket.data),
  })

  const refreshTicket = async (): Promise<TicketDetailPublic> => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] }),
      queryClient.invalidateQueries({ queryKey: ["tickets"] }),
      queryClient.invalidateQueries({ queryKey: ["comments", ticketId] }),
      queryClient.invalidateQueries({ queryKey: ["timeline", ticketId] }),
      queryClient.invalidateQueries({
        queryKey: ["assignment-history", ticketId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["dispatch-candidates", ticketId],
      }),
      queryClient.invalidateQueries({ queryKey: ["notifications"] }),
      queryClient.invalidateQueries({ queryKey: ["overview"] }),
    ])
    return (await TicketsService.readTicket({ path: { ticket_id: ticketId } }))
      .data
  }

  const handleMutationError = async (
    error: Error,
    before?: ConflictSnapshot,
  ) => {
    setActionNotice(null)
    const meta = getApiErrorMeta(error)
    if (isConflictError(error)) {
      setActionError(null)
      setConflict({
        message: extractErrorMessage(error),
        code: meta.code,
        requestId: meta.requestId,
        refreshed: false,
        before,
      })
      const latest = await refreshTicket()
      setConflict((current) =>
        current
          ? {
              ...current,
              refreshed: true,
              after: {
                version: latest.version,
                statusLabel: ticketStatusLabels[latest.status],
              },
            }
          : null,
      )
      return
    }
    setConflict(null)
    setActionError({
      message: extractErrorMessage(error),
      requestId: meta.requestId,
      fields: getApiErrorFields(error),
    })
  }

  const ticketSnapshot = (detail: TicketDetailPublic): ConflictSnapshot => ({
    version: detail.version,
    statusLabel: ticketStatusLabels[detail.status],
  })

  const accept = useMutation({
    mutationFn: async (detail: TicketDetailPublic) => {
      if (!detail.active_assignment) throw new Error("工单没有活动派发")
      return (
        await AssignmentsService.acceptCurrentAssignment({
          path: { assignment_id: detail.active_assignment.id },
          body: {
            expected_ticket_version: detail.version,
            expected_assignment_version: detail.active_assignment.version,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data
    },
    onSuccess: async () => {
      setActionError(null)
      setActionNotice("工单已接受")
      await refreshTicket()
    },
    onError: (error, detail) =>
      handleMutationError(error, ticketSnapshot(detail)),
  })

  const actionMutation = useMutation({
    mutationFn: async ({
      action,
      detail,
      note,
      title,
      description,
    }: {
      action: DialogAction
      detail: TicketDetailPublic
      note: string
      title?: string
      description?: string
    }) => {
      const headers = { "Idempotency-Key": crypto.randomUUID() }
      if (action === "EDIT") {
        return (
          await TicketsService.updateTicket({
            path: { ticket_id: detail.id },
            body: {
              title: title?.trim() || null,
              description: description?.trim() || null,
              expected_version: detail.version,
            },
            headers,
          })
        ).data
      }
      if (action === "CLOSE") {
        return (
          await TicketsService.closeTicket({
            path: { ticket_id: detail.id },
            body: {
              expected_ticket_version: detail.version,
              resolution_note: note.trim() || null,
            },
            headers,
          })
        ).data
      }
      if (action === "REOPEN") {
        return (
          await TicketsService.reopenTicket({
            path: { ticket_id: detail.id },
            body: {
              expected_ticket_version: detail.version,
              reason: note.trim(),
            },
            headers,
          })
        ).data
      }
      if (!detail.active_assignment) throw new Error("工单没有活动派发")
      const assignment = detail.active_assignment
      if (action === "REJECT") {
        return (
          await AssignmentsService.rejectCurrentAssignment({
            path: { assignment_id: assignment.id },
            body: {
              reason: note.trim(),
              expected_ticket_version: detail.version,
              expected_assignment_version: assignment.version,
            },
            headers,
          })
        ).data
      }
      return (
        await AssignmentsService.completeCurrentAssignment({
          path: { assignment_id: assignment.id },
          body: {
            completion_note: note.trim(),
            expected_ticket_version: detail.version,
            expected_assignment_version: assignment.version,
          },
          headers,
        })
      ).data
    },
    onSuccess: async (_, variables) => {
      setDialogAction(null)
      setDialogNote("")
      setActionError(null)
      setActionNotice(
        variables.action === "EDIT"
          ? "工单修改已保存"
          : actionCopy[variables.action].success,
      )
      await refreshTicket()
    },
    onError: (error, variables) =>
      handleMutationError(error, ticketSnapshot(variables.detail)),
  })

  const commentMutation = useMutation({
    mutationFn: async (detail: TicketDetailPublic) =>
      (
        await CommentsService.createComment({
          path: { ticket_id: detail.id },
          body: {
            body: commentBody.trim(),
            expected_ticket_version: detail.version,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setCommentBody("")
      setActionError(null)
      setActionNotice("评论已发布")
      await refreshTicket()
    },
    onError: (error, detail) =>
      handleMutationError(error, ticketSnapshot(detail)),
  })

  if (ticket.isLoading) {
    return (
      <Card>
        <LoadingRows rows={10} />
      </Card>
    )
  }

  if (ticket.isError || !ticket.data) {
    const error = ticket.error ?? new Error("工单不存在")
    const meta = getApiErrorMeta(error)
    const notFound = getApiErrorCode(error) === "TICKET_NOT_FOUND"
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/tickets">
            <ArrowLeft />
            返回工单
          </Link>
        </Button>
        <ErrorState
          title={notFound ? "工单不存在或无权查看" : "工单加载失败"}
          message={extractErrorMessage(error)}
          requestId={meta.requestId}
          forbidden={meta.status === 403}
          onRetry={notFound ? undefined : () => ticket.refetch()}
        />
      </div>
    )
  }

  const detail = ticket.data
  const commentItems = comments.data?.pages.flatMap((page) => page.items) ?? []
  const timelineItems = timeline.data?.pages.flatMap((page) => page.items) ?? []
  const historyItems = history.data?.pages.flatMap((page) => page.items) ?? []
  const action = (name: TicketAction) => hasTicketAction(detail, name)
  const primaryAction = getPrimaryTicketAction(detail.allowed_actions)
  const noteRequired = dialogAction !== null && dialogAction !== "CLOSE"
  const canSubmitDialog =
    dialogAction === "EDIT"
      ? Boolean(editTitle.trim() && editDescription.trim())
      : dialogAction === null
        ? false
        : !noteRequired || Boolean(dialogNote.trim())

  const openEdit = () => {
    setEditTitle(detail.title)
    setEditDescription(detail.description)
    setActionError(null)
    setActionNotice(null)
    setDialogAction("EDIT")
  }

  const closeDialog = () => {
    setDialogAction(null)
    setDialogNote("")
    setActionError(null)
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/tickets">
            <ArrowLeft />
            返回工单
          </Link>
        </Button>
      </div>

      <PageHeader
        eyebrow={`${detail.team.name} · ${detail.id.slice(0, 8)}`}
        title={detail.title}
        description={`提交人：${
          detail.submitter.full_name || detail.submitter.email
        } · 创建于 ${formatDateTime(detail.created_at)}`}
        actions={
          <>
            <StatusBadge kind="ticket" value={detail.status} />
            <span className="rounded-md border bg-muted/50 px-2 py-1 font-mono text-xs text-muted-foreground">
              v{detail.version}
            </span>
            {action("EDIT") ? (
              <Button variant="outline" size="sm" onClick={openEdit}>
                <Pencil />
                编辑
              </Button>
            ) : null}
          </>
        }
      />

      {conflict ? (
        <ConflictBanner
          message={conflict.message}
          code={conflict.code}
          refreshed={conflict.refreshed}
          before={conflict.before}
          after={conflict.after}
          onDismiss={() => setConflict(null)}
        />
      ) : null}
      {actionError && dialogAction === null ? (
        <ActionError
          message={actionError.message}
          requestId={actionError.requestId}
          onDismiss={() => setActionError(null)}
        />
      ) : null}
      {actionNotice ? (
        <p
          className="rounded-lg border border-emerald-500/25 bg-emerald-500/8 px-4 py-2.5 text-sm"
          role="status"
        >
          {actionNotice}
        </p>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex flex-col gap-5">
          <Card>
            <CardHeader>
              <CardTitle>工单内容</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm leading-7">
                {detail.description}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <MessageSquareText className="size-4 text-primary" />
                评论
              </CardTitle>
              <CardDescription>
                与当前工单可见范围一致的公开讨论
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {comments.isLoading ? (
                <LoadingRows rows={2} className="p-0" />
              ) : comments.isError ? (
                <ErrorState
                  message={extractErrorMessage(comments.error)}
                  onRetry={() => comments.refetch()}
                />
              ) : commentItems.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  还没有评论，补充第一条处理信息。
                </p>
              ) : (
                <div className="space-y-3">
                  {commentItems.map((comment) => (
                    <article
                      key={comment.id}
                      className="rounded-lg border bg-card p-3.5"
                    >
                      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">
                          {comment.author.full_name || comment.author.email}
                        </span>
                        <span className="font-mono">
                          {formatDateTime(comment.created_at)}
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-6">
                        {comment.body}
                      </p>
                    </article>
                  ))}
                </div>
              )}
              <DataPager
                hasMore={comments.hasNextPage}
                loading={comments.isFetchingNextPage}
                onLoadMore={() => comments.fetchNextPage()}
              />

              {action("COMMENT") ? (
                <div className="grid gap-2 border-t pt-4">
                  <label htmlFor="new-comment" className="text-xs font-medium">
                    新评论
                  </label>
                  <textarea
                    id="new-comment"
                    aria-label="新评论"
                    aria-invalid={Boolean(actionError?.fields.body)}
                    aria-describedby={
                      actionError?.fields.body
                        ? "comment-body-error"
                        : undefined
                    }
                    className="min-h-24 w-full rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                    maxLength={5000}
                    value={commentBody}
                    onChange={(event) => setCommentBody(event.target.value)}
                    placeholder="补充处理信息或向提交人确认细节…"
                  />
                  <FieldError
                    id="comment-body-error"
                    message={actionError?.fields.body}
                  />
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs text-muted-foreground">
                      {commentBody.length} / 5000
                    </span>
                    <Button
                      size="sm"
                      disabled={
                        !commentBody.trim() || commentMutation.isPending
                      }
                      onClick={() => commentMutation.mutate(detail)}
                    >
                      <Send />
                      {commentMutation.isPending ? "正在发布…" : "发布评论"}
                    </Button>
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock3 className="size-4 text-primary" />
                业务时间线
              </CardTitle>
              <CardDescription>脱敏后的工单生命周期事件</CardDescription>
            </CardHeader>
            <CardContent>
              {timeline.isLoading ? (
                <LoadingRows rows={4} className="p-0" />
              ) : timeline.isError ? (
                <ErrorState
                  message={extractErrorMessage(timeline.error)}
                  onRetry={() => timeline.refetch()}
                />
              ) : timelineItems.length === 0 ? (
                <EmptyState
                  title="暂无时间线事件"
                  description="工单后续操作会按时间出现在这里。"
                />
              ) : (
                <ol
                  className="relative ml-2 border-l pl-6"
                  data-testid="ticket-timeline"
                >
                  {timelineItems.map((event) => (
                    <li key={event.id} className="relative pb-5 last:pb-0">
                      <span className="absolute top-1.5 -left-[29px] size-2.5 rounded-full border-2 border-background bg-primary" />
                      <p className="text-sm font-medium">{event.summary}</p>
                      <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                        {formatDateTime(event.occurred_at)}
                        {event.actor
                          ? ` · ${event.actor.full_name || event.actor.email}`
                          : ""}
                      </p>
                      {event.metadata.note ? (
                        <p className="mt-1.5 text-sm text-muted-foreground">
                          {event.metadata.note}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              )}
              <DataPager
                hasMore={timeline.hasNextPage}
                loading={timeline.isFetchingNextPage}
                onLoadMore={() => timeline.fetchNextPage()}
              />
            </CardContent>
          </Card>
        </div>

        <aside className="flex flex-col gap-5">
          <Card>
            <CardHeader>
              <CardTitle>当前派发</CardTitle>
              <CardDescription>
                {detail.active_assignment ? "活动 Assignment" : "尚未派发"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {detail.active_assignment ? (
                <div className="rounded-lg border bg-card p-3">
                  <div className="flex items-center gap-2">
                    <UserRound className="size-4 text-muted-foreground" />
                    <span className="font-medium">
                      {detail.active_assignment.handler.full_name ||
                        detail.active_assignment.handler.email}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <StatusBadge
                      kind="assignment"
                      value={detail.active_assignment.status}
                    />
                    <span className="font-mono">
                      {formatDateTime(detail.active_assignment.assigned_at)}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  等待 Dispatcher 选择合格处理人。
                </p>
              )}

              <div className="flex flex-col gap-2">
                {action("DISPATCH") ? (
                  <Button
                    asChild
                    variant={
                      primaryAction === "DISPATCH" ? "default" : "outline"
                    }
                  >
                    <Link to="/dispatch" search={{ ticket: detail.id }}>
                      <Bot />
                      进入派发工作台
                    </Link>
                  </Button>
                ) : null}
                {action("ACCEPT") ? (
                  <Button
                    variant={primaryAction === "ACCEPT" ? "default" : "outline"}
                    disabled={accept.isPending}
                    onClick={() => accept.mutate(detail)}
                  >
                    {accept.isPending ? "正在接受…" : "接受工单"}
                  </Button>
                ) : null}
                {action("REJECT") ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setActionError(null)
                      setActionNotice(null)
                      setDialogAction("REJECT")
                    }}
                  >
                    拒绝派发
                  </Button>
                ) : null}
                {action("COMPLETE") ? (
                  <Button
                    variant={
                      primaryAction === "COMPLETE" ? "default" : "outline"
                    }
                    onClick={() => {
                      setActionError(null)
                      setActionNotice(null)
                      setDialogAction("COMPLETE")
                    }}
                  >
                    完成处理
                  </Button>
                ) : null}
                {action("CLOSE") ? (
                  <Button
                    variant={primaryAction === "CLOSE" ? "default" : "outline"}
                    onClick={() => {
                      setActionError(null)
                      setActionNotice(null)
                      setDialogAction("CLOSE")
                    }}
                  >
                    关闭工单
                  </Button>
                ) : null}
                {action("REOPEN") ? (
                  <Button
                    variant={primaryAction === "REOPEN" ? "default" : "outline"}
                    onClick={() => {
                      setActionError(null)
                      setActionNotice(null)
                      setDialogAction("REOPEN")
                    }}
                  >
                    重新打开
                  </Button>
                ) : null}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="size-4 text-primary" />
                派发历史
              </CardTitle>
              <CardDescription>保留重派和拒绝记录</CardDescription>
            </CardHeader>
            <CardContent>
              {history.isLoading ? (
                <LoadingRows rows={2} className="p-0" />
              ) : history.isError ? (
                <p className="text-sm text-destructive">
                  {extractErrorMessage(history.error)}
                </p>
              ) : historyItems.length === 0 ? (
                <p className="text-sm text-muted-foreground">暂无派发历史。</p>
              ) : (
                <div className="space-y-3">
                  {historyItems.map((assignment) => (
                    <div
                      key={assignment.id}
                      className="border-b pb-3 last:border-0 last:pb-0"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium">
                          {assignment.handler.full_name ||
                            assignment.handler.email}
                        </span>
                        <StatusBadge
                          kind="assignment"
                          value={assignment.status}
                        />
                      </div>
                      <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                        {formatDateTime(assignment.assigned_at)} ·{" "}
                        {assignment.dispatch_mode}
                      </p>
                    </div>
                  ))}
                </div>
              )}
              <DataPager
                hasMore={history.hasNextPage}
                loading={history.isFetchingNextPage}
                onLoadMore={() => history.fetchNextPage()}
              />
            </CardContent>
          </Card>
        </aside>
      </div>

      <Dialog
        open={dialogAction !== null}
        onOpenChange={(open) => {
          if (!open) closeDialog()
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {dialogAction === "EDIT"
                ? "编辑工单"
                : dialogAction
                  ? actionCopy[dialogAction].title
                  : "工单操作"}
            </DialogTitle>
            <DialogDescription>
              {dialogAction === "EDIT"
                ? "只有服务端 allowed_actions 允许且工单处于可编辑状态时才可提交。"
                : dialogAction
                  ? actionCopy[dialogAction].description
                  : ""}
            </DialogDescription>
          </DialogHeader>

          {dialogAction && actionError ? (
            <FormErrorSummary
              errors={actionError.fields}
              fieldIdPrefix="edit-ticket"
              fieldIds={{
                reason: "ticket-action-note",
                completion_note: "ticket-action-note",
                resolution_note: "ticket-action-note",
              }}
            />
          ) : null}

          {dialogAction === "EDIT" ? (
            <div className="grid gap-4">
              <label
                htmlFor="edit-ticket-title"
                className="grid gap-2 text-sm font-medium"
              >
                标题
                <Input
                  id="edit-ticket-title"
                  aria-invalid={Boolean(actionError?.fields.title)}
                  aria-describedby={
                    actionError?.fields.title
                      ? "edit-ticket-title-error"
                      : undefined
                  }
                  value={editTitle}
                  maxLength={200}
                  onChange={(event) => setEditTitle(event.target.value)}
                />
                <FieldError
                  id="edit-ticket-title-error"
                  message={actionError?.fields.title}
                />
              </label>
              <label
                htmlFor="edit-ticket-description"
                className="grid gap-2 text-sm font-medium"
              >
                描述
                <textarea
                  id="edit-ticket-description"
                  aria-invalid={Boolean(actionError?.fields.description)}
                  aria-describedby={
                    actionError?.fields.description
                      ? "edit-ticket-description-error"
                      : undefined
                  }
                  className="min-h-36 rounded-lg border bg-background px-3 py-2 text-sm font-normal outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  value={editDescription}
                  maxLength={10000}
                  onChange={(event) => setEditDescription(event.target.value)}
                />
                <FieldError
                  id="edit-ticket-description-error"
                  message={actionError?.fields.description}
                />
              </label>
            </div>
          ) : dialogAction ? (
            <>
              <textarea
                id="ticket-action-note"
                aria-label="操作说明"
                aria-invalid={Boolean(
                  actionError?.fields.reason ||
                    actionError?.fields.completion_note ||
                    actionError?.fields.resolution_note,
                )}
                aria-describedby={
                  actionError?.fields.reason ||
                  actionError?.fields.completion_note ||
                  actionError?.fields.resolution_note
                    ? "ticket-action-note-error"
                    : undefined
                }
                className="min-h-28 rounded-lg border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                value={dialogNote}
                onChange={(event) => setDialogNote(event.target.value)}
                placeholder={
                  dialogAction === "CLOSE"
                    ? "可选：填写解决说明"
                    : actionCopy[dialogAction].placeholder
                }
              />
              <FieldError
                id="ticket-action-note-error"
                message={
                  actionError?.fields.reason ??
                  actionError?.fields.completion_note ??
                  actionError?.fields.resolution_note
                }
              />
            </>
          ) : null}

          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>
              取消
            </Button>
            <Button
              disabled={!canSubmitDialog || actionMutation.isPending}
              onClick={() => {
                if (!dialogAction) return
                actionMutation.mutate({
                  action: dialogAction,
                  detail,
                  note: dialogNote,
                  title: editTitle,
                  description: editDescription,
                })
              }}
            >
              {actionMutation.isPending
                ? "正在提交…"
                : dialogAction === "EDIT"
                  ? "保存修改"
                  : dialogAction
                    ? actionCopy[dialogAction].submit
                    : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
