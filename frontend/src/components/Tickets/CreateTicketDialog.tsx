import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { Plus } from "lucide-react"
import { type ReactNode, useState } from "react"

import {
  TeamsService,
  type TicketCreateRequest,
  TicketsService,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

import { newIdempotencyKey } from "./ticket-ui"

export function CreateTicketDialog({ trigger }: { trigger?: ReactNode }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [open, setOpen] = useState(false)
  const [teamId, setTeamId] = useState("")
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")

  const canCreate = Boolean(
    user?.roles.includes("SUBMITTER") || user?.roles.includes("ADMIN"),
  )
  const teams = useQuery({
    queryKey: ["teams", "create-ticket"],
    queryFn: async () =>
      (await TeamsService.readTeams({ query: { limit: 100 } })).data,
    enabled: canCreate && open,
  })

  const mutation = useMutation({
    mutationFn: async (body: TicketCreateRequest) =>
      (
        await TicketsService.createTicket({
          body,
          headers: { "Idempotency-Key": newIdempotencyKey() },
        })
      ).data,
    onSuccess: async (ticket) => {
      showSuccessToast("工单已创建")
      setOpen(false)
      setTitle("")
      setDescription("")
      await queryClient.invalidateQueries({ queryKey: ["tickets"] })
      navigate({
        to: "/tickets/$ticketId",
        params: { ticketId: ticket.id },
      })
    },
    onError: handleError.bind(showErrorToast),
  })

  if (!canCreate) return null

  const submit = () => {
    if (!teamId || !title.trim() || !description.trim()) return
    mutation.mutate({
      team_id: teamId,
      title: title.trim(),
      description: description.trim(),
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button>
            <Plus />
            新建工单
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建工单</DialogTitle>
          <DialogDescription>
            提交后进入待派发状态，由派单员选择处理人。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2 text-sm font-medium">
            <span>Team</span>
            <Select value={teamId} onValueChange={setTeamId}>
              <SelectTrigger aria-label="Team">
                <SelectValue placeholder="选择 Team" />
              </SelectTrigger>
              <SelectContent>
                {teams.data?.items.map((team) => (
                  <SelectItem key={team.id} value={team.id}>
                    {team.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 text-sm font-medium">
            <span>标题</span>
            <Input
              aria-label="标题"
              maxLength={200}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="grid gap-2 text-sm font-medium">
            <span>描述</span>
            <textarea
              aria-label="描述"
              className="min-h-28 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-[3px]"
              maxLength={10000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          {teams.isError ? (
            <p className="text-sm text-destructive">Team 列表加载失败。</p>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <LoadingButton
            loading={mutation.isPending}
            disabled={!teamId || !title.trim() || !description.trim()}
            onClick={submit}
          >
            创建
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
