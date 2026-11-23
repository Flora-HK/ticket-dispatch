import { useInfiniteQuery } from "@tanstack/react-query"
import { Eye, RefreshCw, Search } from "lucide-react"
import { useState } from "react"

import {
  type AuditAction,
  type AuditEntityType,
  type AuditLogPublic,
  type AuditOutcome,
  AuditService,
} from "@/client"
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "@/components/shared/AsyncState"
import { DataPager } from "@/components/shared/DataPager"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatDateTime } from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { extractErrorMessage, getApiErrorMeta } from "@/utils"

const actions: AuditAction[] = [
  "TICKET_CREATED",
  "TICKET_UPDATED",
  "COMMENT_CREATED",
  "ASSIGNMENT_CREATED",
  "ASSIGNMENT_ACCEPTED",
  "ASSIGNMENT_REJECTED",
  "ASSIGNMENT_COMPLETED",
  "ASSIGNMENT_SUPERSEDED",
  "TICKET_COMPLETED",
  "TICKET_CLOSED",
  "TICKET_REOPENED",
  "USER_ROLES_CHANGED",
  "USER_STATUS_CHANGED",
  "TEAM_MEMBER_CHANGED",
  "AUTO_ASSIGN_FAILED",
]

const entityTypes: AuditEntityType[] = [
  "TICKET",
  "ASSIGNMENT",
  "USER",
  "USER_ROLE",
  "TEAM",
  "TEAM_MEMBERSHIP",
]

type AuditFilters = {
  action?: AuditAction
  outcome?: AuditOutcome
  entityType?: AuditEntityType
  ticketId?: string
  actorId?: string
  createdFrom?: string
  createdTo?: string
  entityKey?: Record<string, string>
}

export function AuditPage() {
  const [draft, setDraft] = useState<AuditFilters>({})
  const [filters, setFilters] = useState<AuditFilters>({})
  const [entityKeyText, setEntityKeyText] = useState("")
  const [filterError, setFilterError] = useState<string | null>(null)
  const [selected, setSelected] = useState<AuditLogPublic | null>(null)

  const audit = useInfiniteQuery({
    queryKey: ["admin-audit", filters],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await AuditService.readAuditLogs({
          query: {
            action: filters.action ?? null,
            outcome: filters.outcome ?? null,
            entity_type: filters.entityType ?? null,
            ticket_id: filters.ticketId?.trim() || null,
            actor_user_id: filters.actorId?.trim() || null,
            entity_key: filters.entityKey
              ? JSON.stringify(filters.entityKey)
              : null,
            created_from: filters.createdFrom
              ? `${filters.createdFrom}T00:00:00`
              : null,
            created_to: filters.createdTo
              ? `${filters.createdTo}T23:59:59`
              : null,
            cursor: pageParam,
            limit: 50,
            sort: "created_at:desc",
          },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })

  const items = audit.data?.pages.flatMap((page) => page.items) ?? []
  const errorMeta = audit.error ? getApiErrorMeta(audit.error) : {}

  const applyFilters = () => {
    let entityKey: Record<string, string> | undefined
    if (entityKeyText.trim()) {
      try {
        const parsed = JSON.parse(entityKeyText) as Record<string, unknown>
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
          throw new Error("entity_key 必须是 JSON 对象")
        }
        entityKey = Object.fromEntries(
          Object.entries(parsed).map(([key, value]) => [key, String(value)]),
        )
      } catch (error) {
        setFilterError(
          error instanceof Error ? error.message : "entity_key JSON 无效",
        )
        return
      }
    }
    setFilterError(null)
    setFilters({ ...draft, entityKey })
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="审计查询"
        description="只读查看关键业务操作、结果和受控详情。原始审计记录不可修改或删除。"
        actions={
          <Button
            variant="outline"
            size="sm"
            disabled={audit.isFetching}
            onClick={() => audit.refetch()}
          >
            <RefreshCw
              className={audit.isFetching ? "animate-spin" : undefined}
            />
            刷新
          </Button>
        }
      />

      <Card>
        <CardHeader className="border-b py-4">
          <p className="text-sm font-medium">查询条件</p>
          <p className="text-xs text-muted-foreground">
            操作筛选以服务端稳定枚举为准。
          </p>
        </CardHeader>
        <CardContent className="grid gap-4 pt-4 md:grid-cols-2 xl:grid-cols-4">
          <FilterSelect
            label="操作"
            value={draft.action ?? "ALL"}
            onChange={(value) =>
              setDraft((current) => ({
                ...current,
                action: value === "ALL" ? undefined : (value as AuditAction),
              }))
            }
            items={actions}
          />
          <FilterSelect
            label="结果"
            value={draft.outcome ?? "ALL"}
            onChange={(value) =>
              setDraft((current) => ({
                ...current,
                outcome: value === "ALL" ? undefined : (value as AuditOutcome),
              }))
            }
            items={["SUCCESS", "FAILED"]}
          />
          <FilterSelect
            label="实体类型"
            value={draft.entityType ?? "ALL"}
            onChange={(value) =>
              setDraft((current) => ({
                ...current,
                entityType:
                  value === "ALL" ? undefined : (value as AuditEntityType),
              }))
            }
            items={entityTypes}
          />
          <div className="grid gap-2 text-xs font-medium">
            <span>工单 ID</span>
            <Input
              aria-label="工单 ID"
              value={draft.ticketId ?? ""}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  ticketId: event.target.value,
                }))
              }
            />
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>Actor 用户 ID</span>
            <Input
              aria-label="Actor 用户 ID"
              value={draft.actorId ?? ""}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  actorId: event.target.value,
                }))
              }
            />
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>开始日期</span>
            <Input
              aria-label="开始日期"
              type="date"
              value={draft.createdFrom ?? ""}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  createdFrom: event.target.value,
                }))
              }
            />
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>结束日期</span>
            <Input
              aria-label="结束日期"
              type="date"
              value={draft.createdTo ?? ""}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  createdTo: event.target.value,
                }))
              }
            />
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>entity_key JSON</span>
            <Input
              aria-label="entity_key JSON"
              value={entityKeyText}
              onChange={(event) => setEntityKeyText(event.target.value)}
              placeholder='{"ticket_id":"..."}'
            />
          </div>
          <div className="flex items-end gap-2 md:col-span-2 xl:col-span-4">
            <Button onClick={applyFilters}>
              <Search />
              应用筛选
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setDraft({})
                setFilters({})
                setEntityKeyText("")
                setFilterError(null)
              }}
            >
              清除
            </Button>
            {filterError ? (
              <p className="text-xs text-destructive">{filterError}</p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden py-0">
        <CardHeader className="border-b py-4">
          <p className="text-sm font-medium">审计记录</p>
          <p className="text-xs text-muted-foreground">
            已加载 {items.length} 条
          </p>
        </CardHeader>
        <CardContent className="p-0">
          {audit.isLoading ? (
            <LoadingRows rows={7} />
          ) : audit.isError ? (
            <ErrorState
              message={extractErrorMessage(audit.error)}
              requestId={errorMeta.requestId}
              forbidden={errorMeta.status === 403}
              onRetry={() => audit.refetch()}
              className="m-4"
            />
          ) : items.length === 0 ? (
            <EmptyState
              title="没有审计记录"
              description="调整筛选条件后再查询。"
            />
          ) : (
            <>
              <div className="hidden lg:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>时间</TableHead>
                      <TableHead>操作</TableHead>
                      <TableHead>结果</TableHead>
                      <TableHead>Actor</TableHead>
                      <TableHead>实体</TableHead>
                      <TableHead>Request ID</TableHead>
                      <TableHead className="w-12" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((entry) => (
                      <TableRow key={entry.id}>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {formatDateTime(entry.created_at)}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          {entry.action}
                        </TableCell>
                        <TableCell>
                          <StatusBadge kind="audit" value={entry.outcome} />
                        </TableCell>
                        <TableCell>
                          {entry.actor?.full_name ||
                            entry.actor?.email ||
                            entry.actor_type}
                        </TableCell>
                        <TableCell className="max-w-52 truncate font-mono text-xs">
                          {entry.entity_type} ·{" "}
                          {entry.entity_id?.slice(0, 8) ?? "—"}
                        </TableCell>
                        <TableCell className="max-w-44 truncate font-mono text-[11px] text-muted-foreground">
                          {entry.request_id}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8"
                            aria-label={`查看审计记录 ${entry.id}`}
                            onClick={() => setSelected(entry)}
                          >
                            <Eye className="size-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="divide-y lg:hidden">
                {items.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className="w-full space-y-2 px-4 py-3 text-left hover:bg-muted/40"
                    onClick={() => setSelected(entry)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-mono text-xs">{entry.action}</span>
                      <StatusBadge kind="audit" value={entry.outcome} />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {entry.entity_type} · {formatDateTime(entry.created_at)}
                    </p>
                  </button>
                ))}
              </div>
              <DataPager
                hasMore={audit.hasNextPage}
                loading={audit.isFetchingNextPage}
                onLoadMore={() => audit.fetchNextPage()}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null)
        }}
      >
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>审计详情 #{selected?.id}</DialogTitle>
            <DialogDescription>
              {selected?.action} ·{" "}
              {selected ? formatDateTime(selected.created_at) : ""}
            </DialogDescription>
          </DialogHeader>
          {selected ? (
            <div className="space-y-4 text-sm">
              <DetailBlock
                title="执行上下文"
                value={{
                  actor_type: selected.actor_type,
                  actor: selected.actor,
                  entity_type: selected.entity_type,
                  entity_id: selected.entity_id,
                  ticket_id: selected.ticket_id,
                  request_id: selected.request_id,
                  error_code: selected.error_code,
                }}
              />
              <DetailBlock
                title="状态快照"
                value={{
                  before: selected.before_state,
                  after: selected.after_state,
                }}
              />
              <DetailBlock
                title="受控详情"
                value={{
                  entity_key: selected.entity_key,
                  detail: selected.detail,
                }}
              />
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  items,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  items: string[]
}) {
  return (
    <div className="grid gap-2 text-xs font-medium">
      <span>{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ALL">全部</SelectItem>
          {items.map((item) => (
            <SelectItem key={item} value={item}>
              {item}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function DetailBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <section>
      <p className="mb-2 text-xs font-semibold tracking-[0.1em] text-muted-foreground uppercase">
        {title}
      </p>
      <pre className="max-h-64 overflow-auto rounded-lg border bg-muted/45 p-3 font-mono text-xs leading-5">
        {JSON.stringify(value, null, 2)}
      </pre>
    </section>
  )
}
