export const auditActionLabels = {
  TICKET_CREATED: "工单创建",
  TICKET_UPDATED: "工单更新",
  COMMENT_CREATED: "评论发布",
  ASSIGNMENT_CREATED: "工单派发",
  ASSIGNMENT_ACCEPTED: "派发被接受",
  ASSIGNMENT_REJECTED: "派发被拒绝",
  ASSIGNMENT_COMPLETED: "处理完成",
  ASSIGNMENT_SUPERSEDED: "派发被替代",
  TICKET_COMPLETED: "工单完成",
  TICKET_CLOSED: "工单关闭",
  TICKET_REOPENED: "工单重开",
  USER_ROLES_CHANGED: "用户角色变更",
  USER_STATUS_CHANGED: "用户状态变更",
  TEAM_MEMBER_CHANGED: "Team 成员变更",
  AUTO_ASSIGN_FAILED: "自动派发失败",
} as const

export const auditEntityLabels = {
  TICKET: "工单",
  ASSIGNMENT: "派发",
  USER: "用户",
  USER_ROLE: "用户角色",
  TEAM: "Team",
  TEAM_MEMBERSHIP: "Team 成员",
} as const

export function getAuditActionLabel(value: string): string {
  return auditActionLabels[value as keyof typeof auditActionLabels] ?? value
}

export function getAuditEntityLabel(value: string): string {
  return auditEntityLabels[value as keyof typeof auditEntityLabels] ?? value
}
