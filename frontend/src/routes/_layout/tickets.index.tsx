import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowRight, RefreshCw } from "lucide-react"
import { useState } from "react"

import { type TicketStatus, TicketsService } from "@/client"
import { CreateTicketDialog } from "@/components/Tickets/CreateTicketDialog"
import { TicketStatusBadge } from "@/components/Tickets/TicketStatusBadge"
import {
  formatDateTime,
  ticketStatusLabels,
} from "@/components/Tickets/ticket-ui"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { extractErrorMessage } from "@/utils"

export const Route = createFileRoute("/_layout/tickets/")({
  component: TicketsPage,
  head: () => ({ meta: [{ title: "工单中心 - 工单派发系统" }] }),
})

function TicketsPage() {
  const [status, setStatus] = useState<string>("ALL")
  const tickets = useQuery({
    queryKey: ["tickets", { status }],
    queryFn: async () =>
      (
        await TicketsService.readTickets({
          query: {
            limit: 100,
            status: status === "ALL" ? null : status,
            sort: "updated_at:desc",
          },
        })
      ).data,
  })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">工单中心</h1>
          <p className="text-muted-foreground">按当前账号可见范围查询工单</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-36" aria-label="工单状态">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">全部状态</SelectItem>
              {(Object.keys(ticketStatusLabels) as TicketStatus[]).map(
                (value) => (
                  <SelectItem key={value} value={value}>
                    {ticketStatusLabels[value]}
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新工单"
            onClick={() => tickets.refetch()}
          >
            <RefreshCw className={tickets.isFetching ? "animate-spin" : ""} />
          </Button>
          <CreateTicketDialog />
        </div>
      </div>

      <Card className="overflow-hidden py-0">
        <CardHeader className="border-b py-5">
          <CardTitle>
            {tickets.data ? `共 ${tickets.data.items.length} 条` : "工单列表"}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {tickets.isLoading ? (
            <div className="p-10 text-center text-muted-foreground">
              正在加载工单…
            </div>
          ) : tickets.isError ? (
            <div className="p-10 text-center text-destructive">
              {extractErrorMessage(tickets.error)}
            </div>
          ) : tickets.data?.items.length === 0 ? (
            <div className="p-12 text-center text-muted-foreground">
              当前筛选条件下没有可见工单。
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>工单</TableHead>
                  <TableHead>Team</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>提交人</TableHead>
                  <TableHead>更新时间</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {tickets.data?.items.map((ticket) => (
                  <TableRow key={ticket.id}>
                    <TableCell>
                      <div className="font-medium">{ticket.title}</div>
                      <div className="font-mono text-xs text-muted-foreground">
                        {ticket.id.slice(0, 8)}
                      </div>
                    </TableCell>
                    <TableCell>{ticket.team.name}</TableCell>
                    <TableCell>
                      <TicketStatusBadge status={ticket.status} />
                    </TableCell>
                    <TableCell>
                      {ticket.submitter.full_name || ticket.submitter.email}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(ticket.updated_at)}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon" asChild>
                        <Link
                          to="/tickets/$ticketId"
                          params={{ ticketId: ticket.id }}
                          aria-label={`打开工单 ${ticket.title}`}
                        >
                          <ArrowRight />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
