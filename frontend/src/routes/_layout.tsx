import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"
import { AppTopbar } from "@/components/app-shell/AppTopbar"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <AppTopbar />
        <div className="min-w-0 flex-1 bg-surface-sunken/60 px-4 py-5 md:px-7 md:py-7">
          <div className="mx-auto min-w-0 max-w-[1500px]">
            <Outlet />
          </div>
        </div>
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}
