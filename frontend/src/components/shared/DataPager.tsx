import { Button } from "@/components/ui/button"

export function DataPager({
  hasMore,
  loading,
  onLoadMore,
  loadedLabel,
}: {
  hasMore: boolean
  loading: boolean
  onLoadMore: () => void
  loadedLabel?: string
}) {
  if (!hasMore) {
    return loadedLabel ? (
      <p className="py-4 text-center text-xs text-muted-foreground">
        {loadedLabel}
      </p>
    ) : null
  }

  return (
    <div className="flex justify-center border-t px-4 py-3">
      <Button
        variant="outline"
        size="sm"
        disabled={loading}
        onClick={onLoadMore}
      >
        {loading ? "正在加载…" : "加载更多"}
      </Button>
    </div>
  )
}
