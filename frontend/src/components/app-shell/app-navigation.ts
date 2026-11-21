import {
  Bell,
  Building2,
  ClipboardList,
  Gauge,
  type LucideIcon,
  ScrollText,
  Ticket,
  UsersRound,
} from "lucide-react"

import type { RoleCode } from "@/client"

export type NavigationItem = {
  title: string
  path: string
  icon: LucideIcon
}

export type NavigationGroup = {
  title: string
  items: NavigationItem[]
}

const overview: NavigationItem = { title: "总览", path: "/", icon: Gauge }
const tickets: NavigationItem = {
  title: "工单",
  path: "/tickets",
  icon: Ticket,
}
const notifications: NavigationItem = {
  title: "通知",
  path: "/notifications",
  icon: Bell,
}
const dispatch: NavigationItem = {
  title: "派发工作台",
  path: "/dispatch",
  icon: ClipboardList,
}

const adminItems: NavigationItem[] = [
  {
    title: "用户与角色",
    path: "/admin/users",
    icon: UsersRound,
  },
  {
    title: "Team 与成员",
    path: "/admin/teams",
    icon: Building2,
  },
  {
    title: "审计查询",
    path: "/admin/audit",
    icon: ScrollText,
  },
]

export function navigationForRoles(
  roles: readonly RoleCode[],
): NavigationGroup[] {
  const canDispatch = roles.includes("DISPATCHER") || roles.includes("ADMIN")
  const workItems = [overview]

  if (canDispatch) {
    workItems.push(dispatch)
  }

  workItems.push(tickets, notifications)

  const groups: NavigationGroup[] = [{ title: "工作", items: workItems }]
  if (roles.includes("ADMIN")) {
    groups.push({ title: "管理", items: adminItems })
  }
  return groups
}
