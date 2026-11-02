
import { describe, it, expect } from 'vitest'
import {
  render,
  screen,
  fireEvent,
} from '@testing-library/react'
import '@testing-library/jest-dom'
import App from './App'

describe('Academia AI Voice Co-Pilot', () => {
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
        name: /Transcript Timeline \(5 messages\)/,
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
})
