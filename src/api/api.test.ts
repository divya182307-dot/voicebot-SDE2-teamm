
import { describe, it, expect } from 'vitest'
import {
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
})
