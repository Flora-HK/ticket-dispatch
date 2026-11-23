import path from "node:path"
import dotenv from "dotenv"

dotenv.config({ path: path.join(import.meta.dirname, "../../.env") })

const apiBase = `${(
  process.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "")}/api/v1`
const demoPassword = "Demo-dispatch-2026!"
const prefix = "[Demo] "

type RoleCode = "SUBMITTER" | "DISPATCHER" | "HANDLER" | "ADMIN"
type User = {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  roles: RoleCode[]
  version: number
}
type Team = {
  id: string
  name: string
  is_active: boolean
  version: number
}
type Ticket = {
  id: string
  title: string
  status: string
  version: number
}
type Page<T> = { items: T[]; next_cursor?: string | null }
type DispatchResponse = {
  ticket: Ticket
  assignment: { id: string; version: number; status: string }
}
type MutationResponse = {
  ticket: Ticket
  changed_assignment: { id: string; version: number; status: string } | null
}

async function login(email: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username: email, password })
  const response = await fetch(`${apiBase}/login/access-token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  })
  if (!response.ok) {
    throw new Error(`Login failed for ${email}: ${response.status}`)
  }
  const data = (await response.json()) as { access_token: string }
  return data.access_token
}

async function api<T>(
  token: string,
  pathname: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set("Authorization", `Bearer ${token}`)
  if (init.method && init.method !== "GET") {
    headers.set("Idempotency-Key", crypto.randomUUID())
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`${apiBase}${pathname}`, {
    ...init,
    headers,
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(
      `${init.method ?? "GET"} ${pathname} failed: ${response.status} ${body}`,
    )
  }
  return (await response.json()) as T
}

async function collect<T>(token: string, pathname: string): Promise<T[]> {
  const items: T[] = []
  let cursor: string | null = null
  do {
    const separator = pathname.includes("?") ? "&" : "?"
    const page: Page<T> = await api<Page<T>>(
      token,
      `${pathname}${separator}limit=100${
        cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""
      }`,
    )
    items.push(...page.items)
    cursor = page.next_cursor ?? null
  } while (cursor)
  return items
}

async function ensureUser(
  adminToken: string,
  email: string,
  fullName: string,
  roles: RoleCode[],
  knownUsers: User[],
): Promise<User> {
  let user = knownUsers.find((item) => item.email === email)
  if (!user) {
    user = await api<User>(adminToken, "/users", {
      method: "POST",
      body: JSON.stringify({
        email,
        password: demoPassword,
        full_name: fullName,
        roles,
      }),
    })
    knownUsers.push(user)
  } else {
    const previousUserId = user.id
    user = await api<User>(adminToken, `/users/${user.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        email,
        full_name: fullName,
        is_active: true,
        password: demoPassword,
        expected_user_version: user.version,
      }),
    })
    const index = knownUsers.findIndex((item) => item.id === previousUserId)
    knownUsers[index] = user
  }

  if (!user) {
    throw new Error(`Unable to ensure demo user ${email}`)
  }
  const currentUser = user
  if (
    currentUser.roles.length !== roles.length ||
    roles.some((role) => !currentUser.roles.includes(role))
  ) {
    const previousUserId = currentUser.id
    user = await api<User>(adminToken, `/users/${currentUser.id}/roles`, {
      method: "PUT",
      body: JSON.stringify({
        roles,
        expected_user_version: currentUser.version,
      }),
    })
    const index = knownUsers.findIndex((item) => item.id === previousUserId)
    knownUsers[index] = user
  }
  return user
}

async function ensureTeam(
  adminToken: string,
  name: string,
  knownTeams: Team[],
): Promise<Team> {
  let team = knownTeams.find((item) => item.name === name)
  if (!team) {
    team = await api<Team>(adminToken, "/teams", {
      method: "POST",
      body: JSON.stringify({ name }),
    })
    knownTeams.push(team)
  } else if (!team.is_active) {
    team = await api<Team>(adminToken, `/teams/${team.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        is_active: true,
        expected_version: team.version,
      }),
    })
    const index = knownTeams.findIndex((item) => item.id === team?.id)
    knownTeams[index] = team
  }
  return team
}

async function ensureMember(adminToken: string, team: Team, userId: string) {
  const currentTeam = await api<Team>(adminToken, `/teams/${team.id}`)
  const members = await collect<{ user: { id: string } }>(
    adminToken,
    `/teams/${team.id}/members`,
  )
  if (members.some((member) => member.user.id === userId)) return
  await api(adminToken, `/teams/${team.id}/members/${userId}`, {
    method: "PUT",
    body: JSON.stringify({
      is_available: true,
      expected_team_version: currentTeam.version,
    }),
  })
}

async function dispatch(
  dispatcherToken: string,
  ticket: Ticket,
  handlerId: string,
): Promise<DispatchResponse> {
  return api<DispatchResponse>(
    dispatcherToken,
    `/tickets/${ticket.id}/dispatch`,
    {
      method: "POST",
      body: JSON.stringify({
        mode: "MANUAL",
        handler_id: handlerId,
        expected_ticket_version: ticket.version,
      }),
    },
  )
}

async function ensureTicket(
  adminToken: string,
  knownTickets: Ticket[],
  teamId: string,
  title: string,
): Promise<{ ticket: Ticket; created: boolean }> {
  const existing = knownTickets.find((ticket) => ticket.title === title)
  if (existing) return { ticket: existing, created: false }
  const ticket = await api<Ticket>(adminToken, "/tickets", {
    method: "POST",
    body: JSON.stringify({
      team_id: teamId,
      title,
      description: `${title}\n\n该数据由 seed:demo 通过真实 API 幂等创建，用于作品集演示负载、派发和异常恢复。`,
    }),
  })
  knownTickets.push(ticket)
  return { ticket, created: true }
}

async function runScenario(
  title: string,
  team: Team,
  handler: User | null,
  state:
    | "PENDING"
    | "ASSIGNED"
    | "IN_PROGRESS"
    | "PENDING_CONFIRMATION"
    | "CLOSED"
    | "REJECTED",
  context: {
    adminToken: string
    dispatcherToken: string
    handlerTokens: Map<string, string>
    knownTickets: Ticket[]
  },
) {
  const { ticket, created } = await ensureTicket(
    context.adminToken,
    context.knownTickets,
    team.id,
    `${prefix}${title}`,
  )
  if (!created || state === "PENDING") return ticket
  if (!handler) throw new Error(`${title} requires a handler`)

  const dispatched = await dispatch(context.dispatcherToken, ticket, handler.id)
  if (state === "ASSIGNED") return dispatched.ticket

  const handlerToken = context.handlerTokens.get(handler.id)
  if (!handlerToken) throw new Error(`Missing handler token for ${title}`)
  if (state === "REJECTED") {
    const rejected = await api<MutationResponse>(
      handlerToken,
      `/assignments/${dispatched.assignment.id}/reject`,
      {
        method: "POST",
        body: JSON.stringify({
          reason: `${title}：当前处理人不具备所需权限`,
          expected_ticket_version: dispatched.ticket.version,
          expected_assignment_version: dispatched.assignment.version,
        }),
      },
    )
    return rejected.ticket
  }
  const acceptedResponse = await api<MutationResponse>(
    handlerToken,
    `/assignments/${dispatched.assignment.id}/accept`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_ticket_version: dispatched.ticket.version,
        expected_assignment_version: dispatched.assignment.version,
      }),
    },
  )
  const accepted = acceptedResponse.ticket
  if (state === "IN_PROGRESS") return accepted

  const completedResponse = await api<MutationResponse>(
    handlerToken,
    `/assignments/${dispatched.assignment.id}/complete`,
    {
      method: "POST",
      body: JSON.stringify({
        completion_note: `${title} 的演示处理说明`,
        expected_ticket_version: accepted.version,
        expected_assignment_version:
          acceptedResponse.changed_assignment?.version ??
          dispatched.assignment.version,
      }),
    },
  )
  const completed = completedResponse.ticket
  if (state === "PENDING_CONFIRMATION") return completed
  if (state === "CLOSED") {
    const closed = await api<MutationResponse>(
      context.adminToken,
      `/tickets/${ticket.id}/actions/close`,
      {
        method: "POST",
        body: JSON.stringify({
          resolution_note: `${title} 已完成并关闭`,
          expected_ticket_version: completed.version,
        }),
      },
    )
    return closed.ticket
  }
  throw new Error(`Unsupported scenario state for ${title}`)
}

async function main() {
  const username = process.env.FIRST_SUPERUSER
  const password = process.env.FIRST_SUPERUSER_PASSWORD
  if (!username || !password) {
    throw new Error("FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD are required")
  }

  const adminToken = await login(username, password)
  const knownUsers = await collect<User>(adminToken, "/users")
  const knownTeams = await collect<Team>(
    adminToken,
    "/teams?include_inactive=true",
  )
  const knownTickets = await collect<Ticket>(adminToken, "/tickets")

  const dispatcher = await ensureUser(
    adminToken,
    "demo.dispatcher@example.com",
    "演示派单员",
    ["DISPATCHER"],
    knownUsers,
  )
  const submitter = await ensureUser(
    adminToken,
    "demo.submitter@example.com",
    "演示提交人",
    ["SUBMITTER"],
    knownUsers,
  )
  const handlers = await Promise.all(
    ["林晨", "周野", "苏桐"].map((name, index) =>
      ensureUser(
        adminToken,
        `demo.handler${index + 1}@example.com`,
        name,
        ["HANDLER"],
        knownUsers,
      ),
    ),
  )

  const operationsTeam = await ensureTeam(adminToken, "运营支持", knownTeams)
  const emptyTeam = await ensureTeam(adminToken, "无候选演示队列", knownTeams)
  for (const handler of handlers) {
    await ensureMember(adminToken, operationsTeam, handler.id)
  }

  const dispatcherToken = await login(dispatcher.email, demoPassword)
  const handlerTokens = new Map<string, string>()
  for (const handler of handlers) {
    handlerTokens.set(handler.id, await login(handler.email, demoPassword))
  }

  const context = {
    adminToken,
    dispatcherToken,
    handlerTokens,
    knownTickets,
  }
  await runScenario(
    "打印机不可用",
    operationsTeam,
    handlers[0],
    "PENDING",
    context,
  )
  await runScenario(
    "共享目录权限异常",
    operationsTeam,
    handlers[1],
    "REJECTED",
    context,
  )
  await runScenario(
    "VPN 连接间歇中断",
    operationsTeam,
    handlers[2],
    "PENDING",
    context,
  )
  await runScenario(
    "新员工账号待处理",
    operationsTeam,
    handlers[0],
    "ASSIGNED",
    context,
  )
  await runScenario(
    "会议室终端离线",
    operationsTeam,
    handlers[0],
    "ASSIGNED",
    context,
  )
  await runScenario(
    "财务系统登录失败",
    operationsTeam,
    handlers[1],
    "IN_PROGRESS",
    context,
  )
  await runScenario(
    "显示器闪烁",
    operationsTeam,
    handlers[2],
    "PENDING_CONFIRMATION",
    context,
  )
  await runScenario(
    "门禁卡权限更新",
    operationsTeam,
    handlers[0],
    "CLOSED",
    context,
  )
  await runScenario("无候选派发演示", emptyTeam, null, "PENDING", context)

  console.log(
    JSON.stringify({
      seeded: true,
      dispatcher: dispatcher.email,
      submitter: submitter.email,
      handlers: handlers.map((handler) => handler.email),
      teams: [operationsTeam.name, emptyTeam.name],
      existingTicketCount: knownTickets.filter((ticket) =>
        ticket.title.startsWith(prefix),
      ).length,
    }),
  )
}

await main()
