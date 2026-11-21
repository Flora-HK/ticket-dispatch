import { CheckCircle2, GitBranch, Layers3 } from "lucide-react"
import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="relative hidden overflow-hidden border-r bg-zinc-950 px-12 py-10 text-white lg:flex lg:flex-col lg:justify-between">
        <Logo variant="full" className="text-white" asLink={false} />
        <div className="max-w-lg">
          <p className="mb-4 text-xs font-semibold tracking-[0.18em] text-blue-300 uppercase">
            Dispatch operations
          </p>
          <h1 className="text-4xl font-semibold tracking-tight text-balance">
            把每一张工单，送到正确的人手里。
          </h1>
          <p className="mt-4 max-w-md text-sm leading-6 text-zinc-400">
            以任务效率和状态可读性为中心，覆盖待办、派发、处理、确认和治理的完整闭环。
          </p>
          <div className="mt-9 grid gap-4 text-sm">
            <Feature
              icon={GitBranch}
              title="可解释的派发"
              description="候选负载、排名和策略结果保持透明。"
            />
            <Feature
              icon={Layers3}
              title="角色化工作台"
              description="Dispatcher、Handler、Submitter 和 Admin 各取所需。"
            />
            <Feature
              icon={CheckCircle2}
              title="真实并发保护"
              description="版本冲突后先刷新资源，再基于最新状态操作。"
            />
          </div>
        </div>
        <p className="text-xs text-zinc-500">
          React · FastAPI · PostgreSQL · OpenAPI
        </p>
      </div>
      <div className="flex flex-col gap-4 p-5 sm:p-8 lg:p-10">
        <div className="flex justify-end">
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <Footer />
      </div>
    </div>
  )
}

function Feature({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof GitBranch
  title: string
  description: string
}) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/5">
        <Icon className="size-4 text-blue-300" />
      </span>
      <div>
        <p className="font-medium text-zinc-100">{title}</p>
        <p className="mt-0.5 text-xs leading-5 text-zinc-400">{description}</p>
      </div>
    </div>
  )
}
