export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t px-6 py-4">
      <p className="text-center text-xs text-muted-foreground">
        Dispatch Desk · 工单派发系统 · {currentYear}
      </p>
    </footer>
  )
}
