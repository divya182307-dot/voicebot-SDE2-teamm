
import type { NewSessionEvent, Session, ApiResponse } from '../types/session'
import { getApiErrorMessage } from './apiError'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS) || 10000;

async function apiRequest<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS,
  );

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      ...init,
      signal: controller.signal,
    })

    const body = await response.json().catch(() => null) as
      | T
      | { data?: T; error?: { message?: string } }
      | null

    if (!response.ok) {
      const errorBody = body as { error?: { message?: string } } | null
      return {
        success: false,
        error: {
          message: errorBody?.error?.message || `Request failed with status ${response.status}`,
          statusCode: response.status,
        },
      }
    }

    const successBody = body as { data?: T } | T | null
    const data = successBody && typeof successBody === 'object' && 'data' in successBody
      ? (successBody as { data: T }).data
      : successBody as T

    return { success: true, data }
  } catch (error) {
    return {
      success: false,
      error: {
        message: controller.signal.aborted
          ? `Request timed out after ${REQUEST_TIMEOUT_MS} ms. Check the backend and try again.`
          : getApiErrorMessage(error),
      },
    }
  } finally {
    window.clearTimeout(timeout);
  }
}

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
  if (import.meta.env.MODE === 'test') {
    return mockRequest({
      sessionId: 'mock-session-001',
      status: 'active',
      message: 'Session started successfully',
    })
  }

  return apiRequest<Session>('/sessions', { method: 'POST' })
}

export async function stopSession(sessionId = 'mock-session-001'): Promise<ApiResponse<Session>> {
  if (import.meta.env.MODE === 'test') {
    return mockRequest({
      sessionId,
      status: 'stopped',
      message: 'Session stopped successfully',
    })
  }

  return apiRequest<Session>(`/sessions/${encodeURIComponent(sessionId)}/stop`, {
    method: 'POST',
  })
}

export async function publishSessionEvent(
  sessionId: string,
  event: Extract<NewSessionEvent, { type: 'workflow' | 'transcript' | 'approval' }>,
): Promise<ApiResponse<{ event: { id: number } }>> {
  return apiRequest<{ event: { id: number } }>(
    `/sessions/${encodeURIComponent(sessionId)}/events`,
    {
      method: 'POST',
      body: JSON.stringify(event),
    },
  )
}

export async function approveAction(sessionId: string): Promise<ApiResponse<{ decision: 'approved' }>> {
  return apiRequest<{ decision: 'approved' }>(
    `/sessions/${encodeURIComponent(sessionId)}/approve`,
    { method: 'POST' }
  )
}

export async function rejectAction(sessionId: string): Promise<ApiResponse<{ decision: 'rejected' }>> {
  return apiRequest<{ decision: 'rejected' }>(
    `/sessions/${encodeURIComponent(sessionId)}/reject`,
    { method: 'POST' }
  )
}
