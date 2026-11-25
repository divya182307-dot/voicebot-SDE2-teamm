
import type { Session, ApiResponse } from '../types/session'
import { getApiErrorMessage } from './apiError'

const MOCK_MODE = import.meta.env.VITE_MOCK_MODE !== 'false'
const API_BASE_URL = '/api'

let activeSessionId: string | null = null

interface BackendSession {
  id: string
  state: string
}

async function backendRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    throw new Error(`Backend request failed (${response.status})`)
  }

  return response.json() as Promise<T>
}

function toFrontendSession(
  session: BackendSession,
  message: string,
): Session {
  return {
    sessionId: session.id,
    status:
      session.state === 'completed' ||
      session.state === 'stopping' ||
      session.state === 'failed' ||
      session.state === 'expired'
        ? 'stopped'
        : 'active',
    message,
  }
}

export async function mockRequest<T>(
  data: T,
  shouldFail = false,
): Promise<ApiResponse<T>> {
  return new Promise((resolve) => {
    setTimeout(() => {
      if (shouldFail) {
        resolve({
          success: false,
          error: {
            message: getApiErrorMessage(
              new Error('Something went wrong. Please try again.'),
            ),
            statusCode: 500,
          },
        })
      } else {
        resolve({ success: true, data })
      }
    }, 500)
  })
}

export async function startSession(): Promise<ApiResponse<Session>> {
  if (MOCK_MODE) {
    return mockRequest({
      sessionId: 'mock-session-001',
      status: 'active',
      message: 'Session started successfully',
    })
  }

  try {
    const created = await backendRequest<{
      session: BackendSession
    }>('/sessions', { method: 'POST' })

    const started = await backendRequest<{
      session: BackendSession
    }>(`/sessions/${created.session.id}/events`, {
      method: 'POST',
      body: JSON.stringify({ event_type: 'start' }),
    })

    activeSessionId = created.session.id

    return {
      success: true,
      data: toFrontendSession(
        started.session,
        'Session started successfully',
      ),
    }
  } catch (error) {
    return {
      success: false,
      error: {
        message: getApiErrorMessage(error),
        statusCode: 500,
      },
    }
  }
}

export async function stopSession(): Promise<ApiResponse<Session>> {
  if (MOCK_MODE) {
    return mockRequest({
      sessionId: 'mock-session-001',
      status: 'stopped',
      message: 'Session stopped successfully',
    })
  }

  if (!activeSessionId) {
    return {
      success: false,
      error: {
        message: 'No active session was found.',
        statusCode: 400,
      },
    }
  }

  try {
    await backendRequest(
      `/sessions/${activeSessionId}/events`,
      {
        method: 'POST',
        body: JSON.stringify({ event_type: 'stop' }),
      },
    )

    const completed = await backendRequest<{
      session: BackendSession
    }>(`/sessions/${activeSessionId}/events`, {
      method: 'POST',
      body: JSON.stringify({ event_type: 'complete' }),
    })

    const result = toFrontendSession(
      completed.session,
      'Session stopped successfully',
    )

    activeSessionId = null

    return { success: true, data: result }
  } catch (error) {
    return {
      success: false,
      error: {
        message: getApiErrorMessage(error),
        statusCode: 500,
      },
    }
  }
}
