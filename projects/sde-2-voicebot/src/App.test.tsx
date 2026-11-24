
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  render,
  screen,
  fireEvent,
  within,
} from '@testing-library/react'
import '@testing-library/jest-dom'

// Mock the audio lifecycle so tests do not need a real microphone.
const audioMock = vi.hoisted(() => ({
  start: vi.fn(),
}))

vi.mock('./audio/audioLifecycle', () => {
  class MockAudioLifecycle {
    status: 'idle' | 'recording' | 'paused' | 'stopped' = 'idle'

    async start() {
      await audioMock.start()
      this.status = 'recording'
    }

    pause() {
      this.status = 'paused'
    }

    resume() {
      this.status = 'recording'
    }

    stop() {
      this.status = 'stopped'
    }
  }

  return {
    AudioLifecycle: MockAudioLifecycle,
  }
})

import App from './App'

describe('Academia AI Voice Co-Pilot', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    audioMock.start.mockResolvedValue(undefined)
  })

  // -----------------------------------------
  // EXISTING APPLICATION TESTS
  // -----------------------------------------

  it('should display the application heading', () => {
    render(<App />)

    expect(
      screen.getByText('Academia AI Voice Co-Pilot')
    ).toBeInTheDocument()
  })

  it('should display the session controls', () => {
    render(<App />)

    expect(
      screen.getByText('Session Controls')
    ).toBeInTheDocument()
  })

  it('should display the transcript timeline', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', {
        name: /Transcript Timeline/,
      })
    ).toBeInTheDocument()
  })

  it('should display the Start Session button', () => {
    render(<App />)

    expect(
      screen.getByRole('button', {
        name: 'Start Session',
      })
    ).toBeInTheDocument()
  })

  it('should add a new transcript message when clicked', () => {
    render(<App />)

    const addButton = screen.getByRole('button', {
      name: 'Add Transcript Message',
    })

    fireEvent.click(addButton)

    expect(
      screen.getByRole('heading', {
        name: /Transcript Timeline \(\s*5 messages\s*\)/,
      })
    ).toBeInTheDocument()

    expect(
      screen.getByText(
        'Here is another example of an AI-generated transcript message.'
      )
    ).toBeInTheDocument()
  })

  it('should display the microphone permission button', () => {
    render(<App />)

    expect(
      screen.getByRole('button', {
        name: 'Request Microphone Permission',
      })
    ).toBeInTheDocument()
  })

  it('should start a session successfully', async () => {
    render(<App />)

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Start Session',
      })
    )

    expect(
      await screen.findByText('Session Status: active')
    ).toBeInTheDocument()

    expect(
      screen.getByText('Session started successfully')
    ).toBeInTheDocument()
  })

  it('should stop a session successfully', async () => {
    render(<App />)

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Start Session',
      })
    )

    await screen.findByText('Session Status: active')

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Stop Session',
      })
    )

    expect(
      await screen.findByText('Session Status: stopped')
    ).toBeInTheDocument()

    expect(
      screen.getByText('Session stopped successfully')
    ).toBeInTheDocument()
  })

  it('should stop an active recording when the session stops', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    await screen.findByText('Session Status: active')
    fireEvent.click(screen.getByRole('button', { name: 'Start Recording' }))
    await screen.findByText('● Recording in progress')

    fireEvent.click(screen.getByRole('button', { name: 'Stop Session' }))

    expect(await screen.findByText('Session Status: stopped')).toBeInTheDocument()
    expect(screen.getByText('Recording stopped')).toBeInTheDocument()
  })

  it('should stop the session immediately while the event stream is disconnected', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    await screen.findByText('Session Status: active')
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    fireEvent.click(screen.getByRole('button', { name: 'Stop Session' }))

    expect(await screen.findByText('Session Status: stopped')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }))

    expect(await screen.findByText('Live Connection Status: connected')).toBeInTheDocument()
    expect(screen.getByText('Session Status: stopped')).toBeInTheDocument()
  })

  it('should stop a microphone that finishes starting after the session is stopped', async () => {
    let resolveStart!: () => void
    audioMock.start.mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveStart = resolve
      })
    )

    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start Recording' }))
    fireEvent.click(screen.getByRole('button', { name: 'Stop Session' }))
    resolveStart()

    expect(await screen.findByText('Session Status: stopped')).toBeInTheDocument()
    expect(await screen.findByText('Recording stopped')).toBeInTheDocument()
  })

  // -----------------------------------------
  // MENTOR FEEDBACK 1: PAUSE AND RESUME
  // -----------------------------------------

  it('should pause and resume recording successfully', async () => {
    render(<App />)

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Start Recording',
      })
    )

    expect(
      await screen.findByText('● Recording in progress')
    ).toBeInTheDocument()

    const pauseButton = screen.getByRole('button', {
      name: 'Pause Recording',
    })

    fireEvent.click(pauseButton)

    expect(
      screen.getByText('Recording paused')
    ).toBeInTheDocument()

    expect(pauseButton).toBeDisabled()

    const resumeButton = screen.getByRole('button', {
      name: 'Resume Recording',
    })

    expect(resumeButton).toBeEnabled()

    fireEvent.click(resumeButton)

    expect(
      screen.getByText('● Recording in progress')
    ).toBeInTheDocument()

    expect(pauseButton).toBeEnabled()
    expect(resumeButton).toBeDisabled()
  })

  // -----------------------------------------
  // MENTOR FEEDBACK 2: INTERIM TO FINAL
  // -----------------------------------------

  it('should convert interim transcript to final and update revision and confidence', () => {
    render(<App />)

    const interimArticle = screen
      .getAllByRole('article')
      .find((article) =>
        article.textContent?.includes('Transcript Type: Interim')
      )

    expect(interimArticle).toBeDefined()

    const article = within(interimArticle!)

    // Check the original interim transcript.
    expect(
      article.getByText(/Interim/)
    ).toBeInTheDocument()

    const originalRevision = Number(
      interimArticle!.textContent?.match(/Revision:\s*(\d+)/)?.[1]
    )

    expect(originalRevision).toBeGreaterThanOrEqual(0)

    // Finalize the interim transcript.
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Finalize Interim Transcript',
      })
    )

    // Check the updated transcript.
    expect(
      article.getByText(/Final/)
    ).toBeInTheDocument()

    expect(
      article.getByText(/94%/)
    ).toBeInTheDocument()

    expect(
      article.getByText('Revised Transcript')
    ).toBeInTheDocument()

    const updatedRevision = Number(
      interimArticle!.textContent?.match(/Revision:\s*(\d+)/)?.[1]
    )

    expect(updatedRevision).toBe(originalRevision + 1)
  })

  // -----------------------------------------
  // MENTOR FEEDBACK 3: LOADING STATE
  // -----------------------------------------

  it('should display the loading state while microphone is starting', async () => {
    let resolveStart!: () => void

    audioMock.start.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveStart = resolve
        })
    )

    render(<App />)

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Start Recording',
      })
    )

    expect(
      screen.getByText('Starting microphone...')
    ).toBeInTheDocument()

    expect(
      screen.getByRole('button', {
        name: 'Start Recording',
      })
    ).toBeDisabled()

    // Complete the mocked microphone startup.
    resolveStart()

    expect(
      await screen.findByText('● Recording in progress')
    ).toBeInTheDocument()

    expect(
      screen.queryByText('Starting microphone...')
    ).not.toBeInTheDocument()
  })

  // -----------------------------------------
  // MENTOR FEEDBACK 3: OFFLINE STATE
  // -----------------------------------------

  it('should display an offline warning when internet is disconnected', () => {
    render(<App />)

    fireEvent(
      window,
      new Event('offline')
    )

    expect(
      screen.getByRole('alert')
    ).toHaveTextContent(
      'You are offline. Please check your internet connection.'
    )
  })

  // -----------------------------------------
  // MENTOR FEEDBACK 4: SCREEN CONTEXT
  // -----------------------------------------

  it('should keep Screen Context OFF by default', () => {
    render(<App />)

    const screenContextCheckbox = screen.getByRole(
      'checkbox',
      {
        name: 'Enable Screen Context',
      }
    )

    expect(screenContextCheckbox).not.toBeChecked()

    expect(
      screen.getByText('Screen Context: OFF')
    ).toBeInTheDocument()

    expect(
      screen.getByText(
        'Screen context is disabled. No screen content is being accessed.'
      )
    ).toBeInTheDocument()

    expect(
      screen.queryByText(
        'Screen context is enabled. You can start screen sharing below when you are ready.'
      )
    ).not.toBeInTheDocument()
  })

  it('should display live backend and workflow sections', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'Live Backend Connection' })).toBeInTheDocument()
    expect(screen.getByText('Live Connection Status: connected')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Workflow Progress' })).toBeInTheDocument()
    expect(screen.getByText('Capture audio')).toBeInTheDocument()
  })

  it('should disconnect and reconnect the live backend', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    expect(await screen.findByText('The live backend is disconnected.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }))
    expect(await screen.findByText('Live Connection Status: connected')).toBeInTheDocument()
  })

  it('should replay workflow events missed during a disconnect', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))

    expect(screen.getByText('Session Status: stopped')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }))

    expect(await screen.findByText('Session Status: active')).toBeInTheDocument()
    expect(await screen.findByText('Replayed 2 missed events.')).toBeInTheDocument()
    expect(screen.getByText('Capture audio').nextSibling).toHaveTextContent('active')
  })

  it('should advance workflow from events published to the live stream', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))

    expect(screen.getByText('Capture audio').nextSibling).toHaveTextContent('active')
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))

    expect(screen.getByText('Capture audio').nextSibling).toHaveTextContent('complete')
    expect(screen.getByText('Build transcript').nextSibling).toHaveTextContent('active')
    expect(await screen.findByText('Actions executed: 0')).toBeInTheDocument()
  })

  it('should explain approval risk and reject without starting execution', () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open Approval Dialog' }))

    expect(screen.getByRole('dialog', { name: 'Approve or Reject Action' })).toBeInTheDocument()
    expect(screen.getByText(/Rejecting records the decision and prevents execution/)).toBeInTheDocument()
    expect(screen.getByText(/Screen context is disabled and will not be used/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    expect(screen.getByText(/Approval Decision: Rejected/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText('Actions executed: 0')).toBeInTheDocument()
    expect(screen.getByText('Approval review').nextSibling).toHaveTextContent('rejected')
  })

  it('should execute only after explicit approval', () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open Approval Dialog' }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(screen.getByText('Actions executed: 1')).toBeInTheDocument()
    expect(screen.getByText('Approval Decision: Approved')).toBeInTheDocument()
  })

  it('should keep keyboard focus inside the approval dialog and allow Escape dismissal', () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open Approval Dialog' }))

    const approveButton = screen.getByRole('button', { name: 'Approve' })
    const rejectButton = screen.getByRole('button', { name: 'Reject' })
    expect(approveButton).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(rejectButton).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText('Actions executed: 0')).toBeInTheDocument()
  })

  it('should snapshot enabled screen context into the approval risk explanation', () => {
    render(<App />)

    fireEvent.click(screen.getByRole('checkbox', { name: 'Enable Screen Context' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start Session' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Advance Workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Open Approval Dialog' }))

    expect(screen.getByText(/and screen context you explicitly shared/)).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveTextContent('Screen context for this action: ON')
  })

  it('should keep screen context off in privacy settings by default', () => {
    render(<App />)

    expect(screen.getByRole('checkbox', { name: 'Enable Screen Context' })).not.toBeChecked()
    expect(screen.getByText('Screen context is OFF.')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox', { name: 'Enable Screen Context' })).toHaveLength(1)
  })

  it('should enable Screen Context only after the user turns it ON', () => {
    render(<App />)

    const screenContextCheckbox = screen.getByRole(
      'checkbox',
      {
        name: 'Enable Screen Context',
      }
    )

    // Initially OFF.
    expect(screenContextCheckbox).not.toBeChecked()

    // User enables Screen Context.
    fireEvent.click(screenContextCheckbox)

    expect(screenContextCheckbox).toBeChecked()

    expect(
      screen.getByText('Screen Context: ON')
    ).toBeInTheDocument()

    expect(
      screen.getByText(
        'Screen context is enabled. You can start screen sharing below when you are ready.'
      )
    ).toBeInTheDocument()

    // User disables Screen Context again.
    fireEvent.click(screenContextCheckbox)

    expect(screenContextCheckbox).not.toBeChecked()

    expect(
      screen.getByText('Screen Context: OFF')
    ).toBeInTheDocument()
  })
})
