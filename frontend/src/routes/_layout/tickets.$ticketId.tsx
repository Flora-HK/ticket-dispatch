import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, Bot, Send, UserRound } from "lucide-react"
import { useState } from "react"

import {
  AssignmentsService,
  CommentsService,
  type TicketAction,
  TicketsService,
} from "@/client"
import { TicketStatusBadge } from "@/components/Tickets/TicketStatusBadge"
import {
  formatDateTime,
  newIdempotencyKey,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import {
  extractErrorMessage,
  getApiErrorCode,
  handleError,
  isConflictError,
} from "@/utils"

export const Route = createFileRoute("/_layout/tickets/$ticketId")({
  component: TicketDetailPage,
})

type DialogAction = "REJECT" | "COMPLETE" | "CLOSE" | "REOPEN"

function TicketDetailPage() {
  const { ticketId } = Route.useParams()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [selectedHandlerId, setSelectedHandlerId] = useState("")
  const [dispatchReason, setDispatchReason] = useState("")
  const [commentBody, setCommentBody] = useState("")
  const [dialogAction, setDialogAction] = useState<DialogAction | null>(null)
  const [dialogNote, setDialogNote] = useState("")

  const ticket = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: async () =>
      (await TicketsService.readTicket({ path: { ticket_id: ticketId } })).data,
  })
  const comments = useQuery({
    queryKey: ["comments", ticketId],
    queryFn: async () =>
      (
        await CommentsService.readComments({
          path: { ticket_id: ticketId },
          query: { limit: 100 },
        })
      ).data,
  })
  const timeline = useQuery({
    queryKey: ["timeline", ticketId],
    queryFn: async () =>
      (
        await TicketsService.readTimeline({
          path: { ticket_id: ticketId },
          query: { limit: 100 },
        })
      ).data,
  })
  const canDispatch = Boolean(
    user?.roles.includes("DISPATCHER") || user?.roles.includes("ADMIN"),
  )
  const candidates = useQuery({
    queryKey: ["dispatch-candidates", ticketId],
    queryFn: async () =>
      (
        await AssignmentsService.getDispatchCandidates({
          path: { ticket_id: ticketId },
        })
      ).data,
    enabled: canDispatch,
  })

  const refreshTicket = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] }),
      queryClient.invalidateQueries({ queryKey: ["tickets"] }),
      queryClient.invalidateQueries({ queryKey: ["timeline", ticketId] }),
      queryClient.invalidateQueries({ queryKey: ["comments", ticketId] }),
      queryClient.invalidateQueries({
        queryKey: ["dispatch-candidates", ticketId],
      }),
      queryClient.invalidateQueries({ queryKey: ["notifications"] }),
    ])
  }

  const mutationError = async (error: Error) => {
    if (isConflictError(error)) {
      await refreshTicket()
    }
    handleError.call(showErrorToast, error)
  }

  const dispatchMutation = useMutation({
    mutationFn: async (mode: "MANUAL" | "AUTO") => {
      if (!ticket.data) throw new Error("Ticket is not loaded")
      const expected = {
        expected_ticket_version: ticket.data.version,
        ...(ticket.data.active_assignment
          ? {
              reason: dispatchReason.trim() || undefined,
              expected_assignment_id: ticket.data.active_assignment.id,
              expected_assignment_version:
                ticket.data.active_assignment.version,
            }
          : {}),
      }
      const body =
        mode === "MANUAL"
          ? {
              mode: "MANUAL" as const,
              handler_id: selectedHandlerId,
              ...expected,
            }
          : {
              mode: "AUTO" as const,
              strategy: "LEAST_OPEN_TICKET" as const,
              ...expected,
            }
      return (
        await AssignmentsService.dispatchTicket({
          path: { ticket_id: ticketId },
          body,
          headers: { "Idempotency-Key": newIdempotencyKey() },
        })
      ).data
    },
    onSuccess: async () => {
      showSuccessToast("派发已完成")
      setSelectedHandlerId("")
      setDispatchReason("")
      await refreshTicket()
    },
    onError: mutationError,
  })

  const acceptMutation = useMutation({
    mutationFn: async () => {
      if (!ticket.data?.active_assignment) throw new Error("No assignment")
      return (
        await AssignmentsService.acceptCurrentAssignment({
          path: { assignment_id: ticket.data.active_assignment.id },
          body: {
            expected_ticket_version: ticket.data.version,
            expected_assignment_version: ticket.data.active_assignment.version,
          },
          headers: { "Idempotency-Key": newIdempotencyKey() },
        })
      ).data
    },
    onSuccess: async () => {
      showSuccessToast("已接受工单")
      await refreshTicket()
    },
    onError: mutationError,
  })

  const dialogMutation = useMutation({
    mutationFn: async () => {
      if (!ticket.data || !dialogAction) throw new Error("No ticket action")
      const headers = { "Idempotency-Key": newIdempotencyKey() }
      if (dialogAction === "CLOSE") {
        return (
          await TicketsService.closeTicket({
            path: { ticket_id: ticketId },
            body: {
              expected_ticket_version: ticket.data.version,
              resolution_note: dialogNote.trim() || null,
            },
            headers,
          })
        ).data
      }
      if (dialogAction === "REOPEN") {
        return (
          await TicketsService.reopenTicket({
            path: { ticket_id: ticketId },
            body: {
              expected_ticket_version: ticket.data.version,
              reason: dialogNote.trim(),
            },
            headers,
          })
        ).data
      }
      if (!ticket.data.active_assignment) throw new Error("No assignment")
      const assignment = ticket.data.active_assignment
      if (dialogAction === "REJECT") {
        return (
          await AssignmentsService.rejectCurrentAssignment({
            path: { assignment_id: assignment.id },
            body: {
              reason: dialogNote.trim(),
              expected_ticket_version: ticket.data.version,
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
            completion_note: dialogNote.trim(),
            expected_ticket_version: ticket.data.version,
            expected_assignment_version: assignment.version,
          },
          headers,
        })
      ).data
    },
    onSuccess: async () => {
      showSuccessToast(
        dialogAction === "CLOSE"
          ? "工单已关闭"
          : dialogAction === "REOPEN"
            ? "工单已重新打开"
            : dialogAction === "REJECT"
              ? "已拒绝派发"
              : "处理已完成",
      )
      setDialogAction(null)
      setDialogNote("")
      await refreshTicket()
    },
    onError: mutationError,
  })

  const commentMutation = useMutation({
    mutationFn: async () => {
      if (!ticket.data) throw new Error("Ticket is not loaded")
      return (
        await CommentsService.createComment({
          path: { ticket_id: ticketId },
          body: {
            body: commentBody.trim(),
            expected_ticket_version: ticket.data.version,
          },
          headers: { "Idempotency-Key": newIdempotencyKey() },
        })
      ).data
    },
    onSuccess: async () => {
      setCommentBody("")
      showSuccessToast("评论已发布")
      await refreshTicket()
    },
    onError: mutationError,
  })

  if (ticket.isLoading) {
    return (
      <div className="p-12 text-center text-muted-foreground">
        正在加载工单…
      </div>
    )
  }
  if (ticket.isError || !ticket.data) {
    const error = ticket.error ?? new Error("工单不存在")
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            {getApiErrorCode(error) === "TICKET_NOT_FOUND"
              ? "工单不存在或无权查看"
              : "工单加载失败"}
          </CardTitle>
          <CardDescription>{extractErrorMessage(error)}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" asChild>
            <Link to="/tickets">返回工单中心</Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  const detail = ticket.data
  const actions = new Set<TicketAction>(detail.allowed_actions)
  const isReassignment = detail.active_assignment !== null
  const needsDispatchReason = isReassignment
  const canSubmitDialogue =
    dialogAction !== "CLOSE" ? dialogNote.trim().length > 0 : true

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/tickets">
            <ArrowLeft />
            返回工单中心
          </Link>
        </Button>
      </div>

      <div className="flex flex-col gap-4 rounded-xl border bg-card p-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-3">
              <TicketStatusBadge status={detail.status} />
              <span className="font-mono text-xs text-muted-foreground">
                v{detail.version}
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">
              {detail.title}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {detail.team.name} ·{" "}
              {detail.submitter.full_name || detail.submitter.email}
            </p>
          </div>
          <p className="text-sm text-muted-foreground">
            更新于 {formatDateTime(detail.updated_at)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/40 p-4 whitespace-pre-wrap">
          {detail.description}
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.has("ACCEPT") ? (
            <Button
              disabled={acceptMutation.isPending}
              onClick={() => acceptMutation.mutate()}
            >
              接受工单
            </Button>
          ) : null}
          {actions.has("REJECT") ? (
            <Button variant="outline" onClick={() => setDialogAction("REJECT")}>
              拒绝派发
            </Button>
          ) : null}
          {actions.has("COMPLETE") ? (
            <Button onClick={() => setDialogAction("COMPLETE")}>
              完成处理
            </Button>
          ) : null}
          {actions.has("CLOSE") ? (
            <Button onClick={() => setDialogAction("CLOSE")}>关闭工单</Button>
          ) : null}
          {actions.has("REOPEN") ? (
            <Button variant="outline" onClick={() => setDialogAction("REOPEN")}>
              重新打开
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>业务时间线</CardTitle>
              <CardDescription>脱敏后的工单生命周期事件</CardDescription>
            </CardHeader>
            <CardContent>
              {timeline.isLoading ? (
                <p className="text-sm text-muted-foreground">加载时间线…</p>
              ) : timeline.data?.items.length ? (
                <ol
                  className="relative ml-3 border-l pl-5"
                  data-testid="ticket-timeline"
                >
                  {timeline.data.items.map((event) => (
                    <li key={event.id} className="relative pb-5 last:pb-0">
                      <span className="absolute top-1.5 -left-[25px] size-2 rounded-full bg-primary" />
                      <p className="font-medium">{event.summary}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDateTime(event.occurred_at)}
                        {event.actor
                          ? ` · ${event.actor.full_name || event.actor.email}`
                          : ""}
                      </p>
                      {event.metadata.note ? (
                        <p className="mt-1 text-sm">{event.metadata.note}</p>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted-foreground">
                  暂无时间线事件。
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>评论</CardTitle>
              <CardDescription>
                与当前工单可见范围一致的公开讨论
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {comments.data?.items.map((comment) => (
                <div key={comment.id} className="rounded-lg border p-3">
                  <div className="mb-1 flex justify-between gap-3 text-xs text-muted-foreground">
                    <span>
                      {comment.author.full_name || comment.author.email}
                    </span>
                    <span>{formatDateTime(comment.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm">{comment.body}</p>
                </div>
              ))}
              {actions.has("COMMENT") ? (
                <div className="flex gap-2">
                  <Input
                    aria-label="新评论"
                    placeholder="补充处理信息…"
                    value={commentBody}
                    onChange={(event) => setCommentBody(event.target.value)}
                  />
                  <Button
                    size="icon"
                    aria-label="发布评论"
                    disabled={!commentBody.trim() || commentMutation.isPending}
                    onClick={() => commentMutation.mutate()}
                  >
                    <Send />
                  </Button>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>当前派发</CardTitle>
              <CardDescription>
                {detail.active_assignment ? "活动 Assignment" : "尚未派发"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {detail.active_assignment ? (
                <div className="flex flex-col gap-1 text-sm">
                  <span className="flex items-center gap-2 font-medium">
                    <UserRound className="size-4" />
                    {detail.active_assignment.handler.full_name ||
                      detail.active_assignment.handler.email}
                  </span>
                  <span className="text-muted-foreground">
                    {detail.active_assignment.status} ·{" "}
                    {formatDateTime(detail.active_assignment.assigned_at)}
                  </span>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  等待派单员选择处理人。
                </p>
              )}
            </CardContent>
          </Card>

          {actions.has("DISPATCH") ? (
            <Card>
              <CardHeader>
                <CardTitle>派发工作台</CardTitle>
                <CardDescription>候选负载由服务端锁内重新计算</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <Select
                  value={selectedHandlerId}
                  onValueChange={setSelectedHandlerId}
                >
                  <SelectTrigger aria-label="处理人">
                    <SelectValue placeholder="选择处理人" />
                  </SelectTrigger>
                  <SelectContent>
                    {candidates.data?.items.map((candidate) => (
                      <SelectItem
                        key={candidate.handler_id}
                        value={candidate.handler_id}
                      >
                        {candidate.handler.full_name || candidate.handler.email}{" "}
                        · 负载 {candidate.open_ticket_count}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {needsDispatchReason ? (
                  <Input
                    aria-label="重派原因"
                    placeholder="重新派发必须填写原因"
                    value={dispatchReason}
                    onChange={(event) => setDispatchReason(event.target.value)}
                  />
                ) : null}
                <Button
                  disabled={
                    !selectedHandlerId ||
                    dispatchMutation.isPending ||
                    (needsDispatchReason && !dispatchReason.trim())
                  }
                  onClick={() => dispatchMutation.mutate("MANUAL")}
                >
                  人工派发
                </Button>
                <Button
                  variant="outline"
                  disabled={
                    dispatchMutation.isPending ||
                    (needsDispatchReason && !dispatchReason.trim())
                  }
                  onClick={() => dispatchMutation.mutate("AUTO")}
                >
                  <Bot />
                  自动选择最低负载
                </Button>
                {candidates.data?.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    当前没有可用候选处理人。
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      <Dialog
        open={dialogAction !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDialogAction(null)
            setDialogNote("")
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogAction === "REJECT"
                ? "拒绝派发"
                : dialogAction === "COMPLETE"
                  ? "完成处理"
                  : dialogAction === "CLOSE"
                    ? "关闭工单"
                    : "重新打开工单"}
            </DialogTitle>
            <DialogDescription>
              {dialogAction === "CLOSE"
                ? "可选填写解决说明。"
                : "请填写原因或处理说明后提交。"}
            </DialogDescription>
          </DialogHeader>
          <textarea
            aria-label="操作说明"
            className="min-h-28 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
            value={dialogNote}
            onChange={(event) => setDialogNote(event.target.value)}
            placeholder={
              dialogAction === "COMPLETE" ? "完成说明" : "原因 / 说明"
            }
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogAction(null)}>
              取消
            </Button>
            <Button
              disabled={!canSubmitDialogue || dialogMutation.isPending}
              onClick={() => dialogMutation.mutate()}
            >
              确认
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
