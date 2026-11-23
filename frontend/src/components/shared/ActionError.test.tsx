import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ActionError, FormErrorSummary } from "./ActionError"

describe("ActionError", () => {
  it("renders a persistent non-conflict error", () => {
    render(<ActionError message="网络连接失败" requestId="request-500" />)

    expect(screen.getByRole("alert")).toHaveTextContent("操作未完成")
    expect(screen.getByText("网络连接失败")).toBeInTheDocument()
    expect(screen.getByText(/request-500/)).toBeInTheDocument()
  })
})

describe("FormErrorSummary", () => {
  it("links summary items to the invalid fields", () => {
    render(
      <FormErrorSummary
        fieldIdPrefix="user"
        errors={{ email: "邮箱格式无效" }}
      />,
    )

    expect(screen.getByRole("link", { name: "邮箱格式无效" })).toHaveAttribute(
      "href",
      "#user-email",
    )
  })
})
