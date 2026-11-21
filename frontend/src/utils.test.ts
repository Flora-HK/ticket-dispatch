import { AxiosError, AxiosHeaders } from "axios"
import { describe, expect, it } from "vitest"

import { getApiErrorMeta } from "./utils"

function apiError(status: number): AxiosError {
  return new AxiosError(
    "Request failed",
    "ERR_BAD_REQUEST",
    undefined,
    undefined,
    {
      status,
      statusText: "Error",
      headers: {},
      config: { headers: new AxiosHeaders() },
      data: {
        error: {
          code: "ACTION_FORBIDDEN",
          message: "当前账号无权执行此操作",
          request_id: "request-123",
        },
      },
    },
  )
}

describe("API error metadata", () => {
  it("exposes stable code and request id for actionable error states", () => {
    expect(getApiErrorMeta(apiError(403))).toEqual({
      status: 403,
      code: "ACTION_FORBIDDEN",
      requestId: "request-123",
    })
  })
})
