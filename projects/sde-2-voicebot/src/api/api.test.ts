
import { describe, it, expect, vi } from 'vitest'
import {
  approveAction,
  rejectAction,
  startSession,
  stopSession,
  mockRequest,
} from './api'

describe('API Client Tests', () => {
  it('should start a session successfully', async () => {
    const response = await startSession()

    expect(response.success).toBe(true)
    expect(response.data?.status).toBe('active')
    expect(response.data?.sessionId).toBe('mock-session-001')
  })

  it('should stop a session successfully', async () => {
    const response = await stopSession()

    expect(response.success).toBe(true)
    expect(response.data?.status).toBe('stopped')
  })

  it('should handle API errors correctly', async () => {
    const response = await mockRequest(
      { message: 'Test data' },
      true
    )

    expect(response.success).toBe(false)
    expect(response.error?.statusCode).toBe(500)
    expect(response.error?.message).toBe(
      'Something went wrong. Please try again.'
    )
  })

  it('should call the real session approval and rejection endpoints', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ decision: 'approved' })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ decision: 'rejected' })))
    vi.stubGlobal('fetch', fetchMock)

    const approved = await approveAction('session/1')
    const rejected = await rejectAction('session/1')

    expect(approved.data?.decision).toBe('approved')
    expect(rejected.data?.decision).toBe('rejected')
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/sessions/session%2F1/approve',
      '/sessions/session%2F1/reject',
    ])
    vi.unstubAllGlobals()
  })
})
