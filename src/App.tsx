
import { useState } from 'react'
import './App.css'
import { startSession, stopSession } from './api/api'
import type { Session, TranscriptMessage } from './types/session'
import { mockTranscript } from './fixtures/transcript'

type MicStatus =
  | 'Permission Not Requested'
  | 'Permission Granted'
  | 'Permission Denied'
  | 'Microphone Not Supported'
  | 'Microphone Error'

function App() {
  const [sessionStarted, setSessionStarted] = useState(false)
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(false)

  const [apiMessage, setApiMessage] = useState('API: Mock Connected')

  const [micStatus, setMicStatus] = useState<MicStatus>(
    'Permission Not Requested'
  )

  const [transcriptMessages, setTranscriptMessages] =
    useState<TranscriptMessage[]>(mockTranscript)

  const handleStartSession = async () => {
    try {
      setLoading(true)

      const response = await startSession()

      if (!response.success || !response.data) {
        throw new Error(
          response.error?.message || 'Unable to start session'
        )
      }

      setSession(response.data)
      setSessionStarted(true)
      setApiMessage(response.data.message)
    } catch (error) {
      setApiMessage(
        error instanceof Error
          ? error.message
          : 'Unable to start session'
      )
    } finally {
      setLoading(false)
    }
  }

  const handleStopSession = async () => {
    try {
      setLoading(true)

      const response = await stopSession()

      if (!response.success || !response.data) {
        throw new Error(
          response.error?.message || 'Unable to stop session'
        )
      }

      setSession(response.data)
      setSessionStarted(false)
      setApiMessage(response.data.message)
    } catch (error) {
      setApiMessage(
        error instanceof Error
          ? error.message
          : 'Unable to stop session'
      )
    } finally {
      setLoading(false)
    }
  }

  const requestMicrophone = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicStatus('Microphone Not Supported')
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      })

      stream.getTracks().forEach((track) => track.stop())

      setMicStatus('Permission Granted')
    } catch (error) {
      if (error instanceof DOMException) {
        if (
          error.name === 'NotAllowedError' ||
          error.name === 'PermissionDeniedError'
        ) {
          setMicStatus('Permission Denied')
        } else {
          setMicStatus('Microphone Error')
        }
      } else {
        setMicStatus('Microphone Error')
      }
    }
  }

  const addTranscriptMessage = () => {
    const newMessage: TranscriptMessage = {
      id: Date.now(),
      speaker: 'AI Assistant',
      text: 'Here is another example of an AI-generated transcript message.',
      timestamp: new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      }),
    }

    setTranscriptMessages((previousMessages) => [
      ...previousMessages,
      newMessage,
    ])
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Academia AI Voice Co-Pilot</h1>

        <div className="header-status">
          <span className="mock-banner">MOCK MODE</span>

          <span className="connection-status" aria-live="polite">
            {apiMessage}
          </span>
        </div>
      </header>

      <main className="main">
        <section
          className="session-card"
          aria-labelledby="session-heading"
        >
          <h2 id="session-heading">Session Controls</h2>

          <p>Start a session to begin your voice interaction.</p>

          <button
            className="start-button"
            onClick={handleStartSession}
            disabled={sessionStarted || loading}
          >
            {loading
              ? 'Please wait...'
              : sessionStarted
                ? 'Session Started'
                : 'Start Session'}
          </button>

          <button
            className="stop-button"
            onClick={handleStopSession}
            disabled={!sessionStarted || loading}
          >
            Stop Session
          </button>

          <p className="status" aria-live="polite">
            Session Status: {session?.status ?? 'Not Started'}
          </p>

          <p className="status">
            Session ID: {session?.sessionId ?? 'Not Available'}
          </p>

          <hr />

          <h3>Microphone Permission</h3>

          <button
            className="start-button"
            onClick={requestMicrophone}
          >
            Request Microphone Permission
          </button>

          <div
            className="status"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            <strong>Microphone Status:</strong>

            <p>{micStatus}</p>

            {micStatus === 'Permission Granted' && (
              <p>Microphone access is ready.</p>
            )}

            {micStatus === 'Permission Denied' && (
              <p>
                Microphone access was denied. Please enable it in
                browser settings.
              </p>
            )}

            {micStatus === 'Microphone Not Supported' && (
              <p>
                Your browser does not support microphone access.
              </p>
            )}

            {micStatus === 'Microphone Error' && (
              <p>
                An error occurred while accessing the microphone.
              </p>
            )}
          </div>
        </section>

        <section
          className="transcript-card"
          aria-labelledby="transcript-heading"
        >
          <h2 id="transcript-heading">
            Transcript Timeline ({transcriptMessages.length} messages)
          </h2>

          <button
            className="start-button"
            onClick={addTranscriptMessage}
          >
            Add Transcript Message
          </button>

          <div
            aria-live="polite"
            aria-relevant="additions"
          >
            {transcriptMessages.map((message) => (
              <article
                className="transcript-item"
                key={message.id}
              >
                <span className="speaker">
                  {message.speaker}
                </span>

                <p>{message.text}</p>

                <small>{message.timestamp}</small>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
