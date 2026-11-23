import { useInfiniteQuery } from "@tanstack/react-query"
import { ChevronDown, Eye, FilterX, RefreshCw, Search, X } from "lucide-react"
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

import { getAuditActionLabel, getAuditEntityLabel } from "./audit-data"

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
  const [advancedOpen, setAdvancedOpen] = useState(false)

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
  const hasFilters = Boolean(
    filters.action ||
      filters.outcome ||
      filters.entityType ||
      filters.ticketId ||
      filters.actorId ||
      filters.createdFrom ||
      filters.createdTo ||
      Object.keys(filters.entityKey ?? {}).length,
  )

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

  const clearFilters = () => {
    setDraft({})
    setFilters({})
    setEntityKeyText("")
    setFilterError(null)
  }

  const removeFilter = (key: keyof AuditFilters) => {
    const nextFilters = { ...filters }
    const nextDraft = { ...draft }
    delete nextFilters[key]
    delete nextDraft[key]
    setFilters(nextFilters)
    setDraft(nextDraft)
    if (key === "entityKey") setEntityKeyText("")
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

      <Card className="py-0">
        <div className="flex flex-wrap items-end gap-2 p-3 md:p-4">
          <FilterSelect
            label="操作"
            value={draft.action ?? "ALL"}
            onChange={(value) =>
              setDraft((current) => ({
                ...current,
                action: value === "ALL" ? undefined : (value as AuditAction),
              }))
            }
            items={actions.map((value) => ({
              value,
              label: getAuditActionLabel(value),
            }))}
            className="min-w-36 flex-1 sm:max-w-52"
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
            items={[
              { value: "SUCCESS", label: "成功" },
              { value: "FAILED", label: "失败" },
            ]}
            className="min-w-28 flex-1 sm:max-w-36"
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
            items={entityTypes.map((value) => ({
              value,
              label: getAuditEntityLabel(value),
            }))}
            className="min-w-32 flex-1 sm:max-w-44"
          />
          <Button
            variant="outline"
            aria-expanded={advancedOpen}
            aria-controls="advanced-audit-filters"
            onClick={() => setAdvancedOpen((open) => !open)}
          >
            <ChevronDown
              className={
                advancedOpen
                  ? "rotate-180 transition-transform"
                  : "transition-transform"
              }
            />
            更多条件
          </Button>
          <Button onClick={applyFilters}>
            <Search />
            应用筛选
          </Button>
          {hasFilters ? (
            <Button variant="ghost" onClick={clearFilters}>
              <FilterX />
              清除
            </Button>
          ) : null}
        </div>

        {hasFilters ? (
          <div className="flex flex-wrap gap-1.5 border-t px-3 py-2.5 md:px-4">
            {filters.action ? (
              <FilterChip
                label={getAuditActionLabel(filters.action)}
                onRemove={() => removeFilter("action")}
              />
            ) : null}
            {filters.outcome ? (
              <FilterChip
                label={filters.outcome === "SUCCESS" ? "成功" : "失败"}
                onRemove={() => removeFilter("outcome")}
              />
            ) : null}
            {filters.entityType ? (
              <FilterChip
                label={getAuditEntityLabel(filters.entityType)}
                onRemove={() => removeFilter("entityType")}
              />
            ) : null}
            {filters.ticketId ? (
              <FilterChip
                label={`工单 ${filters.ticketId.slice(0, 8)}`}
                onRemove={() => removeFilter("ticketId")}
              />
            ) : null}
            {filters.actorId ? (
              <FilterChip
                label={`Actor ${filters.actorId.slice(0, 8)}`}
                onRemove={() => removeFilter("actorId")}
              />
            ) : null}
            {filters.createdFrom ? (
              <FilterChip
                label={`从 ${filters.createdFrom}`}
                onRemove={() => removeFilter("createdFrom")}
              />
            ) : null}
            {filters.createdTo ? (
              <FilterChip
                label={`到 ${filters.createdTo}`}
                onRemove={() => removeFilter("createdTo")}
              />
            ) : null}
            {filters.entityKey ? (
              <FilterChip
                label="实体键"
                onRemove={() => removeFilter("entityKey")}
              />
            ) : null}
          </div>
        ) : null}

        {advancedOpen ? (
          <div
            id="advanced-audit-filters"
            className="grid gap-3 border-t p-3 sm:grid-cols-2 md:p-4 xl:grid-cols-4"
          >
            <AuditFilterField label="工单 ID">
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
            </AuditFilterField>
            <AuditFilterField label="Actor 用户 ID">
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
            </AuditFilterField>
            <AuditFilterField label="开始日期">
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
            </AuditFilterField>
            <AuditFilterField label="结束日期">
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
            </AuditFilterField>
            <AuditFilterField label="entity_key JSON">
              <Input
                aria-label="entity_key JSON"
                value={entityKeyText}
                onChange={(event) => setEntityKeyText(event.target.value)}
                placeholder='{"ticket_id":"..."}'
              />
            </AuditFilterField>
            {filterError ? (
              <p className="text-xs text-destructive sm:col-span-2 xl:col-span-4">
                {filterError}
              </p>
            ) : null}
          </div>
        ) : null}
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
              action={
                hasFilters ? (
                  <Button variant="outline" onClick={clearFilters}>
                    <FilterX />
                    清除筛选
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <>
              <div className="hidden lg:block">
                <Table className="min-w-[980px]">
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
                        <TableCell className="font-mono text-xs tabular-nums text-muted-foreground">
                          {formatDateTime(entry.created_at)}
                        </TableCell>
                        <TableCell>
                          <span className="block text-xs font-medium">
                            {getAuditActionLabel(entry.action)}
                          </span>
                          <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">
                            {entry.action}
                          </span>
                        </TableCell>
                        <TableCell>
                          <StatusBadge kind="audit" value={entry.outcome} />
                        </TableCell>
                        <TableCell>
                          {entry.actor?.full_name ||
                            entry.actor?.email ||
                            entry.actor_type}
                        </TableCell>
                        <TableCell className="max-w-52">
                          <span className="block text-xs">
                            {getAuditEntityLabel(entry.entity_type)}
                          </span>
                          <span className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground">
                            {entry.entity_id?.slice(0, 8) ?? "—"}
                          </span>
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
                    <span className="sr-only">查看审计记录 {entry.id}</span>
                    <div className="flex items-center justify-between gap-3">
                      <span>
                        <span className="block text-sm font-medium">
                          {getAuditActionLabel(entry.action)}
                        </span>
                        <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">
                          {entry.action}
                        </span>
                      </span>
                      <StatusBadge kind="audit" value={entry.outcome} />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {getAuditEntityLabel(entry.entity_type)} ·{" "}
                      {formatDateTime(entry.created_at)}
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
            <DialogTitle>
              {selected ? getAuditActionLabel(selected.action) : "审计详情"}
            </DialogTitle>
            <DialogDescription>
              {selected?.action} · 记录 #{selected?.id} ·{" "}
              {selected ? formatDateTime(selected.created_at) : ""}
            </DialogDescription>
          </DialogHeader>
          {selected ? (
            <div className="space-y-4 text-sm">
              <dl className="grid gap-3 rounded-lg border bg-muted/30 p-3 sm:grid-cols-2">
                <AuditFact
                  label="结果"
                  value={<StatusBadge kind="audit" value={selected.outcome} />}
                />
                <AuditFact
                  label="Actor"
                  value={
                    selected.actor?.full_name ||
                    selected.actor?.email ||
                    selected.actor_type
                  }
                />
                <AuditFact
                  label="实体"
                  value={getAuditEntityLabel(selected.entity_type)}
                />
                <AuditFact
                  label="实体 ID"
                  value={selected.entity_id?.slice(0, 8) ?? "—"}
                  mono
                />
                {selected.ticket_id ? (
                  <AuditFact
                    label="工单 ID"
                    value={selected.ticket_id.slice(0, 8)}
                    mono
                  />
                ) : null}
                {selected.error_code ? (
                  <AuditFact label="错误码" value={selected.error_code} mono />
                ) : null}
                <AuditFact
                  label="Request ID"
                  value={selected.request_id}
                  mono
                />
              </dl>
              <details className="rounded-lg border">
                <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium">
                  查看原始 JSON
                </summary>
                <div className="space-y-4 border-t p-3">
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
              </details>
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
  className,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  items: Array<{ value: string; label: string }>
  className?: string
}) {
  return (
    <div className={`grid gap-2 text-xs font-medium ${className ?? ""}`}>
      <span>{label}</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ALL">全部</SelectItem>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function AuditFilterField({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-2 text-xs font-medium">
      <span>{label}</span>
      {children}
    </div>
  )
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string
  onRemove: () => void
}) {
  return (
    <button
      type="button"
      className="inline-flex min-h-8 max-md:min-h-11 items-center gap-1 rounded-md border bg-muted/45 px-2 text-xs font-medium hover:bg-muted"
      aria-label={`移除筛选 ${label}`}
      onClick={onRemove}
    >
      {label}
      <X className="size-3.5" />
    </button>
  )
}

function AuditFact({
  label,
  value,
  mono = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={
          mono ? "mt-0.5 break-all font-mono text-xs" : "mt-0.5 text-sm"
        }
      >
        {value}
      </dd>
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
