import { AxiosError, AxiosHeaders } from "axios"
import { describe, expect, it } from "vitest"

import { getApiErrorFields, getApiErrorMeta } from "./utils"

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

  it("maps validation fields to their stable client-side field names", () => {
    const error = apiError(422)
    if (!error.response) throw new Error("Missing response")
    error.response.data = {
      error: {
        code: "VALIDATION_ERROR",
        message: "请求内容无效",
        request_id: "request-422",
        details: {
          fields: [
            {
              loc: ["body", "email"],
              message: "邮箱格式无效",
              type: "string_format",
            },
            {
              loc: ["body", "roles"],
              message: "至少选择一个角色",
              type: "list_length",
            },
          ],
        },
      },
    }

    expect(getApiErrorFields(error)).toEqual({
      email: "邮箱格式无效",
      roles: "至少选择一个角色",
    })
  })
})
