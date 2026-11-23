import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { Building2, Plus, RefreshCw, UserMinus, UserPlus } from "lucide-react"
import { useEffect, useState } from "react"

import {
  type TeamMembershipPublic,
  type TeamPublic,
  TeamsService,
  UsersService,
} from "@/client"
import {
  ActionError,
  FieldError,
  FormErrorSummary,
} from "@/components/shared/ActionError"
import {
  EmptyState,
  ErrorState,
  InlineLoading,
  LoadingRows,
} from "@/components/shared/AsyncState"
import {
  ConflictBanner,
  type ConflictSnapshot,
} from "@/components/shared/ConflictBanner"
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
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  extractErrorMessage,
  getApiErrorFields,
  getApiErrorMeta,
  isConflictError,
} from "@/utils"

type TeamDialogMode = "CREATE" | "EDIT" | null
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

export function TeamsPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [dialogMode, setDialogMode] = useState<TeamDialogMode>(null)
  const [teamName, setTeamName] = useState("")
  const [teamActive, setTeamActive] = useState(true)
  const [editingTeam, setEditingTeam] = useState<TeamPublic | null>(null)
  const [newMemberId, setNewMemberId] = useState("")
  const [conflict, setConflict] = useState<ConflictState | null>(null)
  const [actionError, setActionError] = useState<ActionErrorState | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)

  const teams = useInfiniteQuery({
    queryKey: ["admin-teams"],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await TeamsService.readTeams({
          query: {
            cursor: pageParam,
            limit: 50,
            include_inactive: true,
          },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
  const teamItems = teams.data?.pages.flatMap((page) => page.items) ?? []

  useEffect(() => {
    if (!selectedId && teamItems[0]) setSelectedId(teamItems[0].id)
  }, [selectedId, teamItems])

  const selectedTeam = teamItems.find((team) => team.id === selectedId) ?? null
  const members = useInfiniteQuery({
    queryKey: ["admin-team-members", selectedId],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await TeamsService.readTeamMembers({
          path: { team_id: selectedId! },
          query: { cursor: pageParam, limit: 50 },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: Boolean(selectedId),
  })
  const users = useQuery({
    queryKey: ["admin-users", "member-picker"],
    queryFn: async () =>
      (await UsersService.readUsers({ query: { limit: 100 } })).data,
  })

  const refreshTeams = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin-teams"] }),
      queryClient.invalidateQueries({
        queryKey: ["admin-team-members", selectedId],
      }),
      queryClient.invalidateQueries({ queryKey: ["overview"] }),
    ])
  }

  const memberPages = members.data?.pages
  const memberItems = memberPages?.flatMap((page) => page.items) ?? []
  const memberTeamVersion =
    (memberPages ? memberPages[memberPages.length - 1] : undefined)
      ?.team_version ??
    selectedTeam?.version ??
    0

  const teamSnapshot = (team: TeamPublic): ConflictSnapshot => ({
    version: team.version,
    statusLabel: team.is_active ? "启用" : "停用",
  })

  const mutationError = async (error: Error, beforeTeam?: TeamPublic) => {
    setActionNotice(null)
    const meta = getApiErrorMeta(error)
    if (isConflictError(error)) {
      setActionError(null)
      setConflict({
        message: extractErrorMessage(error),
        code: meta.code,
        requestId: meta.requestId,
        refreshed: false,
        before: beforeTeam ? teamSnapshot(beforeTeam) : undefined,
      })
      await refreshTeams()
      const latest = beforeTeam
        ? (await TeamsService.readTeam({ path: { team_id: beforeTeam.id } }))
            .data
        : undefined
      setConflict((current) =>
        current
          ? {
              ...current,
              refreshed: true,
              after: latest ? teamSnapshot(latest) : undefined,
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

  const createTeam = useMutation({
    mutationFn: async () =>
      (
        await TeamsService.createTeam({
          body: { name: teamName.trim() },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async (team) => {
      setSelectedId(team.id)
      setDialogMode(null)
      setTeamName("")
      setActionError(null)
      setActionNotice("Team 已创建")
      await refreshTeams()
    },
    onError: (error) => mutationError(error),
  })

  const updateTeam = useMutation({
    mutationFn: async (team: TeamPublic) =>
      (
        await TeamsService.updateTeam({
          path: { team_id: team.id },
          body: {
            name: teamName.trim() || null,
            is_active: teamActive,
            expected_version: team.version,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setDialogMode(null)
      setEditingTeam(null)
      setActionError(null)
      setActionNotice("Team 已更新")
      await refreshTeams()
    },
    onError: (error, team) => mutationError(error, team),
  })

  const upsertMember = useMutation({
    mutationFn: async ({
      userId,
      available,
    }: {
      userId: string
      available: boolean
    }) =>
      (
        await TeamsService.upsertMember({
          path: {
            team_id: selectedId!,
            user_id: userId,
          },
          body: {
            is_available: available,
            expected_team_version: memberTeamVersion,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setNewMemberId("")
      setActionError(null)
      setActionNotice("成员状态已更新")
      await refreshTeams()
    },
    onError: (error) => mutationError(error, selectedTeam ?? undefined),
  })

  const removeMember = useMutation({
    mutationFn: async (member: TeamMembershipPublic) =>
      (
        await TeamsService.deleteMember({
          path: {
            team_id: selectedId!,
            user_id: member.user.id,
          },
          query: { expected_team_version: memberTeamVersion },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setActionError(null)
      setActionNotice("成员已移除")
      await refreshTeams()
    },
    onError: (error) => mutationError(error, selectedTeam ?? undefined),
  })

  const openCreate = () => {
    setEditingTeam(null)
    setTeamName("")
    setTeamActive(true)
    setActionError(null)
    setActionNotice(null)
    setDialogMode("CREATE")
  }

  const openEdit = (team: TeamPublic) => {
    setEditingTeam(team)
    setTeamName(team.name)
    setTeamActive(team.is_active)
    setActionError(null)
    setActionNotice(null)
    setDialogMode("EDIT")
  }

  const memberIds = new Set(memberItems.map((member) => member.user.id))
  const availableUsers = users.data?.items.filter(
    (user) => !memberIds.has(user.id) && user.is_active,
  )
  const errorMeta = teams.error ? getApiErrorMeta(teams.error) : {}

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Team 与成员"
        description="维护派发队列、启用状态和处理人可用性。所有变更使用 Team 版本保护。"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={teams.isFetching}
              onClick={() => teams.refetch()}
            >
              <RefreshCw
                className={teams.isFetching ? "animate-spin" : undefined}
              />
              刷新
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus />
              新建 Team
            </Button>
          </>
        }
      />

      {conflict && dialogMode === null ? (
        <ConflictBanner
          message={conflict.message}
          code={conflict.code}
          refreshed={conflict.refreshed}
          before={conflict.before}
          after={conflict.after}
          onDismiss={() => setConflict(null)}
        />
      ) : null}
      {actionError && dialogMode === null ? (
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

      <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="overflow-hidden py-0">
          <CardHeader className="border-b py-4">
            <CardTitle>Team 列表</CardTitle>
            <CardDescription>{teamItems.length} 个队列</CardDescription>
          </CardHeader>
          <CardContent className="max-h-[680px] overflow-auto p-0">
            {teams.isLoading ? (
              <LoadingRows rows={6} />
            ) : teams.isError ? (
              <ErrorState
                message={extractErrorMessage(teams.error)}
                requestId={errorMeta.requestId}
                onRetry={() => teams.refetch()}
                className="m-3"
              />
            ) : teamItems.length === 0 ? (
              <EmptyState
                title="还没有 Team"
                description="创建第一个派发队列。"
              />
            ) : (
              <div className="divide-y">
                {teamItems.map((team) => (
                  <button
                    key={team.id}
                    type="button"
                    onClick={() => setSelectedId(team.id)}
                    className={`flex w-full items-start justify-between gap-3 px-4 py-3.5 text-left hover:bg-muted/50 ${
                      selectedId === team.id ? "bg-primary/7" : ""
                    }`}
                  >
                    <span>
                      <span className="block font-medium">{team.name}</span>
                      <span className="mt-1 block font-mono text-[11px] text-muted-foreground">
                        v{team.version} · {formatDateTime(team.created_at)}
                      </span>
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] ${
                        team.is_active
                          ? "bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {team.is_active ? "启用" : "停用"}
                    </span>
                  </button>
                ))}
                <DataPager
                  hasMore={teams.hasNextPage}
                  loading={teams.isFetchingNextPage}
                  onLoadMore={() => teams.fetchNextPage()}
                />
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          {!selectedTeam ? (
            <EmptyState
              title="选择一个 Team"
              description="从左侧选择队列查看成员。"
            />
          ) : (
            <>
              <CardHeader className="border-b">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <Building2 className="size-4 text-primary" />
                      {selectedTeam.name}
                    </CardTitle>
                    <CardDescription>
                      版本 v{memberTeamVersion} ·{" "}
                      {selectedTeam.is_active ? "可派发" : "已停用"}
                    </CardDescription>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openEdit(selectedTeam)}
                  >
                    编辑 Team
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-5 pt-5">
                <div className="flex flex-col gap-2 rounded-lg border bg-muted/35 p-3 sm:flex-row sm:items-end">
                  <div className="grid flex-1 gap-1.5 text-xs font-medium">
                    <span>添加处理人</span>
                    <Select value={newMemberId} onValueChange={setNewMemberId}>
                      <SelectTrigger aria-label="添加处理人">
                        <SelectValue placeholder="选择账号" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableUsers?.map((user) => (
                          <SelectItem key={user.id} value={user.id}>
                            {user.full_name || user.email}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    disabled={!newMemberId || upsertMember.isPending}
                    onClick={() =>
                      upsertMember.mutate({
                        userId: newMemberId,
                        available: true,
                      })
                    }
                  >
                    <UserPlus />
                    添加
                  </Button>
                </div>

                {members.isLoading ? (
                  <LoadingRows rows={5} className="p-0" />
                ) : members.isError ? (
                  <ErrorState
                    message={extractErrorMessage(members.error)}
                    onRetry={() => members.refetch()}
                  />
                ) : memberItems.length === 0 ? (
                  <EmptyState
                    title="暂无成员"
                    description="添加 Handler 账号后，该 Team 才能参与派发。"
                  />
                ) : (
                  <div className="divide-y rounded-lg border">
                    {memberItems.map((member) => (
                      <div
                        key={member.id}
                        className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">
                            {member.user.full_name || member.user.email}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {member.user.email}
                          </p>
                          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                            最近派发：
                            {member.last_assigned_at
                              ? formatDateTime(member.last_assigned_at)
                              : "无"}
                          </p>
                        </div>
                        <div className="flex items-center gap-2">
                          <div className="flex items-center gap-2 text-xs">
                            <Checkbox
                              aria-label={`${member.user.full_name || member.user.email}可用`}
                              checked={member.is_available}
                              onCheckedChange={(checked) =>
                                upsertMember.mutate({
                                  userId: member.user.id,
                                  available: checked === true,
                                })
                              }
                            />
                            可用
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8 text-muted-foreground"
                            aria-label={`移除 ${member.user.full_name || member.user.email}`}
                            disabled={removeMember.isPending}
                            onClick={() => removeMember.mutate(member)}
                          >
                            <UserMinus className="size-4" />
                          </Button>
                        </div>
                      </div>
                    ))}
                    <DataPager
                      hasMore={members.hasNextPage}
                      loading={members.isFetchingNextPage}
                      onLoadMore={() => members.fetchNextPage()}
                    />
                  </div>
                )}
                {upsertMember.isPending || removeMember.isPending ? (
                  <InlineLoading label="正在更新成员" />
                ) : null}
              </CardContent>
            </>
          )}
        </Card>
      </div>

      <Dialog
        open={dialogMode !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDialogMode(null)
            setActionError(null)
            setActionNotice(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialogMode === "CREATE" ? "新建 Team" : "编辑 Team"}
            </DialogTitle>
            <DialogDescription>
              Team 是派发队列；停用后不会再成为新派发目标。
            </DialogDescription>
          </DialogHeader>
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
          {actionError ? (
            <>
              <FormErrorSummary
                errors={actionError.fields}
                fieldIdPrefix="team"
                fieldIds={{ name: "team-name", is_active: "team-active" }}
              />
              {Object.keys(actionError.fields).length === 0 ? (
                <ActionError
                  message={actionError.message}
                  requestId={actionError.requestId}
                  onDismiss={() => setActionError(null)}
                />
              ) : null}
            </>
          ) : null}
          <div className="grid gap-4">
            <div className="grid gap-2 text-sm font-medium">
              <span>Team 名称</span>
              <Input
                id="team-name"
                aria-label="Team 名称"
                aria-invalid={Boolean(actionError?.fields.name)}
                aria-describedby={
                  actionError?.fields.name ? "team-name-error" : undefined
                }
                value={teamName}
                maxLength={100}
                onChange={(event) => setTeamName(event.target.value)}
              />
              <FieldError
                id="team-name-error"
                message={actionError?.fields.name}
              />
            </div>
            {dialogMode === "EDIT" ? (
              <div className="flex items-center gap-2">
                <Checkbox
                  id="team-active"
                  checked={teamActive}
                  onCheckedChange={(checked) => setTeamActive(checked === true)}
                />
                <Label htmlFor="team-active">启用 Team</Label>
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDialogMode(null)
                setActionError(null)
                setActionNotice(null)
              }}
            >
              取消
            </Button>
            <Button
              disabled={
                !teamName.trim() || createTeam.isPending || updateTeam.isPending
              }
              onClick={() => {
                if (dialogMode === "CREATE") createTeam.mutate()
                else if (editingTeam) updateTeam.mutate(editingTeam)
              }}
            >
              {createTeam.isPending || updateTeam.isPending
                ? "正在提交…"
                : dialogMode === "CREATE"
                  ? "创建 Team"
                  : "保存 Team"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
