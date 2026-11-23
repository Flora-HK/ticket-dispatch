import { AxiosError } from "axios"

interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
    request_id?: string
    details?: {
      fields?: Array<{
        loc?: unknown[]
        message?: string
        msg?: string
      }>
    }
  }
}

function apiErrorBody(err: AxiosError<ApiErrorBody>): ApiErrorBody | undefined {
  return err.response?.data
}

export function extractErrorMessage(err: Error): string {
  if (err instanceof AxiosError) {
    const data = apiErrorBody(err)
    if (data?.error?.message) {
      return data.error.message
    }
    const errDetail = (err.response?.data as { detail?: unknown } | undefined)
      ?.detail
    if (Array.isArray(errDetail) && errDetail.length > 0) {
      return errDetail[0].msg
    }
    if (typeof errDetail === "string") {
      return errDetail
    }
    return err.message
  }
  return "Something went wrong."
}

export function getApiErrorCode(err: Error): string | undefined {
  if (!(err instanceof AxiosError)) return undefined
  return apiErrorBody(err)?.error?.code
}

export function getApiErrorMeta(err: Error): {
  status?: number
  code?: string
  requestId?: string
} {
  if (!(err instanceof AxiosError)) return {}
  const detail = apiErrorBody(err)?.error
  return {
    status: err.response?.status,
    code: detail?.code,
    requestId: detail?.request_id,
  }
}

export function getApiErrorFields(err: Error): Record<string, string> {
  if (!(err instanceof AxiosError)) return {}
  const fields = apiErrorBody(err)?.error?.details?.fields
  if (!Array.isArray(fields)) return {}

  return fields.reduce<Record<string, string>>((result, field) => {
    const key = [...(field.loc ?? [])]
      .reverse()
      .find((segment): segment is string => typeof segment === "string")
    const message = field.message ?? field.msg
    if (key && message) result[key] = message
    return result
  }, {})
}

export function isConflictError(err: Error): boolean {
  return err instanceof AxiosError && err.response?.status === 409
}

export const handleError = function (this: (msg: string) => void, err: Error) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
