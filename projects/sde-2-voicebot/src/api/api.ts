
import type { Session, ApiResponse } from '../types/session'
import { getApiErrorMessage } from './apiError'

const MOCK_MODE = true
const MOCK_ERROR = false

export async function mockRequest<T>(
  data: T,
  shouldFail = false
): Promise<ApiResponse<T>> {
  return new Promise((resolve) => {
    setTimeout(() => {
      if (shouldFail) {
        resolve({
          success: false,
          error: {
            message: getApiErrorMessage(
              new Error('Something went wrong. Please try again.')
            ),
            statusCode: 500,
          },
        })
      } else {
        resolve({
          success: true,
          data,
        })
      }
    }, 500)
  })
}

export async function startSession(): Promise<ApiResponse<Session>> {
  if (MOCK_MODE) {
    return mockRequest(
      {
        sessionId: 'mock-session-001',
        status: 'active',
        message: 'Session started successfully',
      },
      MOCK_ERROR
    )
  }

  return {
    success: false,
    error: {
      message: 'API server is not configured.',
      statusCode: 503,
    },
  }
}

export async function stopSession(): Promise<ApiResponse<Session>> {
  if (MOCK_MODE) {
    return mockRequest(
      {
        sessionId: 'mock-session-001',
        status: 'stopped',
        message: 'Session stopped successfully',
      },
      MOCK_ERROR
    )
  }

  return {
    success: false,
    error: {
      message: 'API server is not configured.',
      statusCode: 503,
    },
  }
}
