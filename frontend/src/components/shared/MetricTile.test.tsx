import { render, screen } from "@testing-library/react"
import { TriangleAlert } from "lucide-react"
import { describe, expect, it } from "vitest"

import { MetricTile } from "./MetricTile"

describe("MetricTile", () => {
  it("uses neutral semantics when a danger metric is zero", () => {
    const { container } = render(
      <MetricTile
        label="异常提醒"
        value={0}
        detail="超时或负载失衡"
        icon={TriangleAlert}
        tone="danger"
      />,
    )

    expect(container.firstElementChild).toHaveAttribute("data-tone", "neutral")
    expect(screen.getByText("异常提醒")).toBeInTheDocument()
  })

  it("keeps the requested tone when the metric is greater than zero", () => {
    const { container } = render(
      <MetricTile
        label="异常提醒"
        value={2}
        detail="超时或负载失衡"
        icon={TriangleAlert}
        tone="danger"
      />,
    )

    expect(container.firstElementChild).toHaveAttribute("data-tone", "danger")
    expect(screen.getByText("2")).toBeInTheDocument()
  })
})
