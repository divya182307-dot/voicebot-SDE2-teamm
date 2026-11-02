
export interface Session {
  sessionId: string
  status: 'active' | 'stopped'
  message: string
}

export interface ApiError {
  message: string
  statusCode?: number
}

export interface TranscriptMessage {
  id: number
  speaker: 'Student' | 'AI Assistant'
  text: string
  timestamp: string
}

export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: ApiError
}
