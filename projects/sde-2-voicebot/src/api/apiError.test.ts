
import { describe, it, expect } from 'vitest'
import {
  getApiErrorMessage,
  createApiError,
} from './apiError'

describe('API Error Handler Tests', () => {
  it('should return an error message from an Error object', () => {
    const error = new Error('Network connection failed')

    expect(getApiErrorMessage(error)).toBe(
      'Network connection failed'
    )
  })

  it('should return a default message for unknown errors', () => {
    expect(getApiErrorMessage('Unknown error')).toBe(
      'Something went wrong. Please try again.'
    )
  })

  it('should create an API error with a status code', () => {
    const error = createApiError('Server error', 500)

    expect(error.message).toBe('Server error')
    expect(error.statusCode).toBe(500)
  })

  it('should use 500 as the default status code', () => {
    const error = createApiError('Unexpected error')

    expect(error.statusCode).toBe(500)
  })
})
