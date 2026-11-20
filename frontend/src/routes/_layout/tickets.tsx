import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/tickets")({
  component: TicketsLayout,
})

function TicketsLayout() {
  return <Outlet />
}
