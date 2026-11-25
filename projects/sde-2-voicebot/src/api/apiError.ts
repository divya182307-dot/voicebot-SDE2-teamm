
import type { ApiError } from '../types/session'

export function getApiErrorMessage(
  error: unknown
): string {
  if (error instanceof Error) {
    return error.message
  }

  return 'Something went wrong. Please try again.'
}

export function createApiError(
  message: string,
  statusCode = 500
): ApiError {
  return {
    message,
    statusCode,
  }
}
