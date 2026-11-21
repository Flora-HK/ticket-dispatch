import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import {
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react"
import { useState } from "react"

import { type RoleCode, type UserPublic, UsersService } from "@/client"
import {
  EmptyState,
  ErrorState,
  LoadingRows,
} from "@/components/shared/AsyncState"
import { ConflictBanner } from "@/components/shared/ConflictBanner"
import { DataPager } from "@/components/shared/DataPager"
import { PageHeader } from "@/components/shared/PageHeader"
import { StatusBadge } from "@/components/shared/StatusBadge"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { extractErrorMessage, getApiErrorMeta, isConflictError } from "@/utils"

const roleOptions: RoleCode[] = ["SUBMITTER", "DISPATCHER", "HANDLER", "ADMIN"]

type UserDialogMode = "CREATE" | "EDIT" | "ROLES"

type FormState = {
  email: string
  fullName: string
  password: string
  isActive: boolean
  roles: RoleCode[]
}

const emptyForm: FormState = {
  email: "",
  fullName: "",
  password: "",
  isActive: true,
  roles: ["SUBMITTER"],
}

export function UsersPage() {
  const queryClient = useQueryClient()
  const [role, setRole] = useState("ALL")
  const [active, setActive] = useState("ALL")
  const [mode, setMode] = useState<UserDialogMode | null>(null)
  const [selectedUser, setSelectedUser] = useState<UserPublic | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [conflict, setConflict] = useState<{
    message: string
    refreshed: boolean
  } | null>(null)

  const users = useInfiniteQuery({
    queryKey: ["admin-users", { role, active }],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await UsersService.readUsers({
          query: {
            cursor: pageParam,
            limit: 50,
            role: role === "ALL" ? null : role,
            is_active: active === "ALL" ? null : active === "ACTIVE",
          },
        })
      ).data,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
      queryClient.invalidateQueries({ queryKey: ["currentUser"] }),
      queryClient.invalidateQueries({ queryKey: ["overview"] }),
    ])
  }

  const mutationError = async (error: Error) => {
    setConflict({ message: extractErrorMessage(error), refreshed: false })
    if (isConflictError(error)) {
      await refresh()
    }
    setConflict((current) => (current ? { ...current, refreshed: true } : null))
  }

  const createUser = useMutation({
    mutationFn: async () =>
      (
        await UsersService.createUser({
          body: {
            email: form.email.trim(),
            password: form.password,
            full_name: form.fullName.trim() || null,
            roles: form.roles,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setMode(null)
      setForm(emptyForm)
      await refresh()
    },
    onError: mutationError,
  })

  const updateUser = useMutation({
    mutationFn: async (user: UserPublic) =>
      (
        await UsersService.updateUser({
          path: { user_id: user.id },
          body: {
            email: form.email.trim() || null,
            full_name: form.fullName.trim() || null,
            is_active: form.isActive,
            ...(form.password ? { password: form.password } : {}),
            expected_user_version: user.version,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setMode(null)
      await refresh()
    },
    onError: mutationError,
  })

  const replaceRoles = useMutation({
    mutationFn: async (user: UserPublic) =>
      (
        await UsersService.replaceRoles({
          path: { user_id: user.id },
          body: {
            roles: form.roles,
            expected_user_version: user.version,
          },
          headers: { "Idempotency-Key": crypto.randomUUID() },
        })
      ).data,
    onSuccess: async () => {
      setMode(null)
      await refresh()
    },
    onError: mutationError,
  })

  const openCreate = () => {
    setForm(emptyForm)
    setSelectedUser(null)
    setMode("CREATE")
  }

  const openEdit = (user: UserPublic) => {
    setSelectedUser(user)
    setForm({
      email: user.email,
      fullName: user.full_name ?? "",
      password: "",
      isActive: user.is_active,
      roles: [...user.roles],
    })
    setMode("EDIT")
  }

  const openRoles = (user: UserPublic) => {
    setSelectedUser(user)
    setForm({
      email: user.email,
      fullName: user.full_name ?? "",
      password: "",
      isActive: user.is_active,
      roles: [...user.roles],
    })
    setMode("ROLES")
  }

  const errorMeta = users.error ? getApiErrorMeta(users.error) : {}
  const items = users.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow="Administration"
        title="用户与角色"
        description="管理账号资料、启用状态和固定角色集合。角色变化会立即影响后续请求权限。"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={users.isFetching}
              onClick={() => users.refetch()}
            >
              <RefreshCw
                className={users.isFetching ? "animate-spin" : undefined}
              />
              刷新
            </Button>
            <Button size="sm" onClick={openCreate}>
              <Plus />
              新建账号
            </Button>
          </>
        }
      />

      {conflict ? (
        <ConflictBanner
          message={conflict.message}
          refreshed={conflict.refreshed}
          onDismiss={() => setConflict(null)}
        />
      ) : null}

      <Card>
        <CardContent className="grid gap-4 pt-5 sm:grid-cols-2">
          <div className="grid gap-2 text-xs font-medium">
            <span>角色</span>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger aria-label="角色筛选">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">全部角色</SelectItem>
                {roleOptions.map((code) => (
                  <SelectItem key={code} value={code}>
                    {code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2 text-xs font-medium">
            <span>账号状态</span>
            <Select value={active} onValueChange={setActive}>
              <SelectTrigger aria-label="账号状态筛选">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">全部状态</SelectItem>
                <SelectItem value="ACTIVE">启用</SelectItem>
                <SelectItem value="INACTIVE">停用</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden py-0">
        <CardHeader className="border-b py-4">
          <CardTitle>账号列表</CardTitle>
          <CardDescription>{items.length} 个账号</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {users.isLoading ? (
            <LoadingRows rows={7} />
          ) : users.isError ? (
            <ErrorState
              message={extractErrorMessage(users.error)}
              requestId={errorMeta.requestId}
              forbidden={errorMeta.status === 403}
              onRetry={() => users.refetch()}
              className="m-4"
            />
          ) : items.length === 0 ? (
            <EmptyState
              title="没有符合条件的账号"
              description="调整筛选或创建新的演示账号。"
            />
          ) : (
            <>
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>用户</TableHead>
                      <TableHead>角色</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>版本</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((user) => (
                      <TableRow key={user.id}>
                        <TableCell>
                          <p className="font-medium">
                            {user.full_name || "未填写姓名"}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {user.email}
                          </p>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {user.roles.map((code) => (
                              <StatusBadge
                                key={code}
                                kind="role"
                                value={code}
                              />
                            ))}
                          </div>
                        </TableCell>
                        <TableCell>
                          <span
                            className={
                              user.is_active
                                ? "text-sm text-emerald-700 dark:text-emerald-300"
                                : "text-sm text-muted-foreground"
                            }
                          >
                            {user.is_active ? "启用" : "停用"}
                          </span>
                        </TableCell>
                        <TableCell className="font-mono text-xs">
                          v{user.version}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openEdit(user)}
                            >
                              <Pencil />
                              资料
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => openRoles(user)}
                            >
                              <ShieldCheck />
                              角色
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="divide-y md:hidden">
                {items.map((user) => (
                  <div key={user.id} className="space-y-3 p-4">
                    <div>
                      <p className="font-medium">
                        {user.full_name || "未填写姓名"}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {user.email} · v{user.version}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {user.roles.map((code) => (
                        <StatusBadge key={code} kind="role" value={code} />
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openEdit(user)}
                      >
                        编辑资料
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openRoles(user)}
                      >
                        调整角色
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              <DataPager
                hasMore={users.hasNextPage}
                loading={users.isFetchingNextPage}
                onLoadMore={() => users.fetchNextPage()}
              />
            </>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={mode !== null}
        onOpenChange={(open) => {
          if (!open) setMode(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {mode === "CREATE"
                ? "新建账号"
                : mode === "ROLES"
                  ? "调整角色"
                  : "编辑账号"}
            </DialogTitle>
            <DialogDescription>
              {mode === "ROLES"
                ? "角色集合会全量替换，并校验服务端账号版本。"
                : selectedUser
                  ? `当前版本 v${selectedUser.version}`
                  : "创建后可继续调整角色和启用状态。"}
            </DialogDescription>
          </DialogHeader>

          {mode === "ROLES" ? (
            <RoleChecklist
              selected={form.roles}
              onChange={(roles) =>
                setForm((current) => ({ ...current, roles }))
              }
            />
          ) : (
            <div className="grid gap-4">
              <div className="grid gap-2 text-sm font-medium">
                <span>邮箱</span>
                <Input
                  aria-label="邮箱"
                  type="email"
                  value={form.email}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      email: event.target.value,
                    }))
                  }
                />
              </div>
              <div className="grid gap-2 text-sm font-medium">
                <span>姓名</span>
                <Input
                  aria-label="姓名"
                  value={form.fullName}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      fullName: event.target.value,
                    }))
                  }
                />
              </div>
              <div className="grid gap-2 text-sm font-medium">
                <span>
                  {mode === "CREATE" ? "初始密码" : "重置密码（可选）"}
                </span>
                <Input
                  aria-label={
                    mode === "CREATE" ? "初始密码" : "重置密码（可选）"
                  }
                  type="password"
                  value={form.password}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      password: event.target.value,
                    }))
                  }
                />
              </div>
              {mode === "CREATE" ? (
                <RoleChecklist
                  selected={form.roles}
                  onChange={(roles) =>
                    setForm((current) => ({ ...current, roles }))
                  }
                />
              ) : (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="user-active"
                    checked={form.isActive}
                    onCheckedChange={(checked) =>
                      setForm((current) => ({
                        ...current,
                        isActive: checked === true,
                      }))
                    }
                  />
                  <Label htmlFor="user-active">账号启用</Label>
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setMode(null)}>
              取消
            </Button>
            <Button
              disabled={
                createUser.isPending ||
                updateUser.isPending ||
                replaceRoles.isPending ||
                !form.email.trim() ||
                form.roles.length === 0 ||
                (mode === "CREATE" && form.password.length < 8)
              }
              onClick={() => {
                if (mode === "CREATE") createUser.mutate()
                else if (mode === "ROLES" && selectedUser)
                  replaceRoles.mutate(selectedUser)
                else if (selectedUser) updateUser.mutate(selectedUser)
              }}
            >
              {createUser.isPending ||
              updateUser.isPending ||
              replaceRoles.isPending
                ? "正在提交…"
                : mode === "ROLES"
                  ? "保存角色"
                  : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function RoleChecklist({
  selected,
  onChange,
}: {
  selected: RoleCode[]
  onChange: (roles: RoleCode[]) => void
}) {
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-2 flex items-center gap-2 text-sm font-medium">
        <KeyRound className="size-4 text-primary" />
        角色
      </legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {roleOptions.map((role) => {
          const checked = selected.includes(role)
          return (
            <div
              key={role}
              className="flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm"
            >
              <Checkbox
                aria-label={`角色 ${role}`}
                checked={checked}
                onCheckedChange={(next) => {
                  if (next === true) onChange([...selected, role])
                  else onChange(selected.filter((item) => item !== role))
                }}
              />
              <UserRound className="size-4 text-muted-foreground" />
              {role}
            </div>
          )
        })}
      </div>
    </fieldset>
  )
}
