import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { ArrowRight, FilterX, RefreshCw, SlidersHorizontal } from "lucide-react"

import { TeamsService, type TicketStatus, TicketsService } from "@/client"
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "@/components/shared/AsyncState"
import { DataPager } from "@/components/shared/DataPager"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { CreateTicketDialog } from "@/components/Tickets/CreateTicketDialog"
import {
  formatDateTime,
  ticketStatusLabels,
} from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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

export type TicketListSearch = {
  team_id?: string
  submitter_id?: string
  status?: TicketStatus
  assigned_to_me?: boolean
  created_from?: string
  created_to?: string
  sort?: string
}

const sortOptions = [
  { value: "updated_at:desc", label: "最近更新" },
  { value: "created_at:desc", label: "最新创建" },
  { value: "created_at:asc", label: "最早创建" },
]

export function TicketListPage({ search }: { search: TicketListSearch }) {
  const navigate = useNavigate()
  const teams = useQuery({
    queryKey: ["teams", "ticket-filter"],
    queryFn: async () =>
      (await TeamsService.readTeams({ query: { limit: 100 } })).data,
  })
  const tickets = useInfiniteQuery({
    queryKey: ["tickets", "infinite", search],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await TicketsService.readTickets({
          query: {
            team_id: search.team_id ?? null,
            submitter_id: search.submitter_id?.trim() || null,
            status: search.status ?? null,
            assigned_to_me: search.assigned_to_me ?? false,
            created_from: search.created_from
              ? `${search.created_from}T00:00:00`
              : null,
            created_to: search.created_to
              ? `${search.created_to}T23:59:59`
              : null,
            cursor: pageParam,
            limit: 25,
            sort: search.sort ?? "updated_at:desc",
          },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })

  const items = tickets.data?.pages.flatMap((page) => page.items) ?? []
  const hasFilters = Boolean(
    search.team_id ||
      search.submitter_id ||
      search.status ||
      search.assigned_to_me ||
      search.created_from ||
      search.created_to,
  )
  const errorMeta = tickets.error ? getApiErrorMeta(tickets.error) : {}

  const patchSearch = (patch: Partial<TicketListSearch>) => {
    void navigate({
      to: "/tickets",
      search: (previous) => {
        const next = { ...previous, ...patch }
        for (const [key, value] of Object.entries(next)) {
          if (value === "" || value === undefined) {
            delete next[key as keyof TicketListSearch]
          }
        }
        return next
      },
      replace: true,
    })
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="工单"
        description="按服务端可见范围查询和处理工单。筛选条件保留在地址栏中。"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={tickets.isFetching}
              onClick={() => tickets.refetch()}
            >
              <RefreshCw
                className={tickets.isFetching ? "animate-spin" : undefined}
              />
              刷新
            </Button>
            <CreateTicketDialog />
          </>
        }
      />

      <Card>
        <CardHeader className="border-b py-4">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">筛选与排序</span>
            {hasFilters ? (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() =>
                  void navigate({
                    to: "/tickets",
                    search: {
                      sort: search.sort ?? "updated_at:desc",
                    },
                    replace: true,
                  })
                }
              >
                <FilterX />
                清除筛选
              </Button>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 pt-4 md:grid-cols-2 xl:grid-cols-6">
          <FilterField label="Team">
            <Select
              value={search.team_id ?? "ALL"}
              onValueChange={(value) =>
                patchSearch({ team_id: value === "ALL" ? undefined : value })
              }
            >
              <SelectTrigger aria-label="Team">
                <SelectValue placeholder="全部 Team" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">全部 Team</SelectItem>
                {teams.data?.items.map((team) => (
                  <SelectItem key={team.id} value={team.id}>
                    {team.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="状态">
            <Select
              value={search.status ?? "ALL"}
              onValueChange={(value) =>
                patchSearch({
                  status: value === "ALL" ? undefined : (value as TicketStatus),
                })
              }
            >
              <SelectTrigger aria-label="状态">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">全部状态</SelectItem>
                {(Object.keys(ticketStatusLabels) as TicketStatus[]).map(
                  (status) => (
                    <SelectItem key={status} value={status}>
                      {ticketStatusLabels[status]}
                    </SelectItem>
                  ),
                )}
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="提交人 ID">
            <Input
              aria-label="提交人 ID"
              value={search.submitter_id ?? ""}
              onChange={(event) =>
                patchSearch({
                  submitter_id: event.target.value || undefined,
                })
              }
              placeholder="用户 UUID"
            />
          </FilterField>

          <FilterField label="创建时间从">
            <Input
              type="date"
              aria-label="创建时间从"
              value={search.created_from ?? ""}
              onChange={(event) =>
                patchSearch({ created_from: event.target.value || undefined })
              }
            />
          </FilterField>

          <FilterField label="创建时间到">
            <Input
              type="date"
              aria-label="创建时间到"
              value={search.created_to ?? ""}
              onChange={(event) =>
                patchSearch({ created_to: event.target.value || undefined })
              }
            />
          </FilterField>

          <FilterField label="排序">
            <Select
              value={search.sort ?? "updated_at:desc"}
              onValueChange={(value) => patchSearch({ sort: value })}
            >
              <SelectTrigger aria-label="排序">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sortOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          <div className="flex items-center gap-2 md:col-span-2 xl:col-span-6">
            <Checkbox
              id="assigned-to-me"
              checked={search.assigned_to_me ?? false}
              onCheckedChange={(checked) =>
                patchSearch({
                  assigned_to_me: checked === true ? true : undefined,
                })
              }
            />
            <Label htmlFor="assigned-to-me">只看派发给我的工单</Label>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden py-0">
        <CardHeader className="flex-row items-center justify-between border-b py-4">
          <div>
            <p className="font-medium">工单队列</p>
            <p className="mt-1 text-xs text-muted-foreground">
              已加载 {items.length} 条
            </p>
          </div>
          <StatusBadge kind="ticket" value={search.status ?? "ALL"} />
        </CardHeader>
        <CardContent className="p-0">
          {tickets.isLoading ? (
            <LoadingRows rows={7} />
          ) : tickets.isError ? (
            <ErrorState
              message={extractErrorMessage(tickets.error)}
              requestId={errorMeta.requestId}
              forbidden={errorMeta.status === 403}
              onRetry={() => tickets.refetch()}
              className="m-4"
            />
          ) : items.length === 0 ? (
            <EmptyState
              title="没有符合条件的工单"
              description={
                hasFilters
                  ? "尝试清除筛选或调整查询条件。"
                  : "当前账号的可见范围内还没有工单。"
              }
            />
          ) : (
            <>
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>工单</TableHead>
                      <TableHead>Team</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>提交人</TableHead>
                      <TableHead>更新时间</TableHead>
                      <TableHead>版本</TableHead>
                      <TableHead className="w-12" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((ticket) => (
                      <TableRow key={ticket.id}>
                        <TableCell className="max-w-sm">
                          <p className="truncate font-medium">{ticket.title}</p>
                          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                            {ticket.id.slice(0, 8)}
                          </p>
                        </TableCell>
                        <TableCell>{ticket.team.name}</TableCell>
                        <TableCell>
                          <StatusBadge kind="ticket" value={ticket.status} />
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {ticket.submitter.full_name || ticket.submitter.email}
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {formatDateTime(ticket.updated_at)}
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          v{ticket.version}
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8"
                            asChild
                          >
                            <Link
                              to="/tickets/$ticketId"
                              params={{ ticketId: ticket.id }}
                              aria-label={`打开工单 ${ticket.title}`}
                            >
                              <ArrowRight className="size-4" />
                            </Link>
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="divide-y md:hidden">
                {items.map((ticket) => (
                  <Link
                    key={ticket.id}
                    to="/tickets/$ticketId"
                    params={{ ticketId: ticket.id }}
                    className="block px-4 py-3.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="line-clamp-2 text-sm font-medium">
                        {ticket.title}
                      </p>
                      <StatusBadge kind="ticket" value={ticket.status} />
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
                      <span>
                        {ticket.team.name} ·{" "}
                        {ticket.submitter.full_name || ticket.submitter.email}
                      </span>
                      <span className="font-mono">
                        {formatDateTime(ticket.updated_at)}
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
              <DataPager
                hasMore={tickets.hasNextPage}
                loading={tickets.isFetchingNextPage}
                onLoadMore={() => tickets.fetchNextPage()}
              />
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function FilterField({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-2">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </div>
  )
}
