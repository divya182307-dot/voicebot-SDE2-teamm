
import { useEffect, useRef, useState } from "react";
import MicrophoneSelector from "./components/MicrophoneSelector";
import ScreenCapture from "./components/ScreenCapture";
import {
  AudioLifecycle,
  type AudioStatus,
} from "./audio/audioLifecycle";
import type { TranscriptMessage } from "./types/session";
import { mockTranscript } from "./fixtures/transcript";
import "./App.css";

function App() {
  const [isSessionActive, setIsSessionActive] = useState(false);

  const [recordingStatus, setRecordingStatus] =
    useState<AudioStatus>("idle");

  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  // Screen context is OFF by default.
  const [isScreenContextEnabled, setIsScreenContextEnabled] =
    useState(false);

  // Internet connection status.
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const audioLifecycle = useRef<AudioLifecycle | null>(null);

  if (audioLifecycle.current === null) {
    audioLifecycle.current = new AudioLifecycle();
  }

  const [messages, setMessages] = useState<TranscriptMessage[]>([
    mockTranscript[0],
    mockTranscript[1],
    mockTranscript[2],
    mockTranscript[4],
  ]);

  // Start session.
  const handleStart = () => {
    setIsSessionActive(true);
  };

  // Stop session.
  const handleStop = () => {
    setIsSessionActive(false);
  };

  // Start recording.
  const handleStartRecording = async () => {
    setIsLoading(true);
    setErrorMessage("");

    try {
      await audioLifecycle.current!.start();
      setRecordingStatus("recording");
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Unable to start recording."
      );
    } finally {
      setIsLoading(false);
    }
  };

  // Pause recording.
  const handlePauseRecording = () => {
    audioLifecycle.current!.pause();
    setRecordingStatus(audioLifecycle.current!.status);
  };

  // Resume recording.
  const handleResumeRecording = () => {
    audioLifecycle.current!.resume();
    setRecordingStatus(audioLifecycle.current!.status);
  };

  // Stop recording.
  const handleStopRecording = () => {
    audioLifecycle.current!.stop();
    setRecordingStatus("stopped");
  };

  // Add transcript message.
  const handleAddMessage = () => {
    const newMessage: TranscriptMessage = {
      id: Math.max(0, ...messages.map((message) => message.id)) + 1,
      speaker: "AI Assistant",
      text: "Here is another example of an AI-generated transcript message.",
      timestamp: new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      type: "final",
      confidence: 0.95,
      revision: 1,
      isRevised: false,
    };

    setMessages((previousMessages) => [
      ...previousMessages,
      newMessage,
    ]);
  };

  // Finalize interim transcript.
  const handleFinalizeTranscript = () => {
    setMessages((previousMessages) =>
      previousMessages.map((message) =>
        message.type === "interim"
          ? {
              ...message,
              type: "final",
              confidence: 0.94,
              revision: message.revision + 1,
              isRevised: true,
            }
          : message
      )
    );
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Academia AI Voice Co-Pilot</h1>
        <p>Your AI-powered academic voice assistant</p>
      </header>

      <main className="app-main">

        {/* Offline warning */}
        {!isOnline && (
          <div
            role="alert"
            style={{
              backgroundColor: "#ffe0e0",
              color: "#b00020",
              padding: "12px",
              borderRadius: "8px",
              marginBottom: "15px",
            }}
          >
            You are offline. Please check your internet connection.
          </div>
        )}

        {/* Mock mode */}
        <div className="mock-banner">
          <strong>Mock Mode Active</strong>
          <p>
            This application currently uses mock data for development
            and testing.
          </p>
        </div>

        {/* Session controls */}
        <section className="session-section">
          <h2>Session Controls</h2>

          <p>
            Session Status:{" "}
            {isSessionActive ? "active" : "stopped"}
          </p>

          <div className="session-buttons">
            <button
              type="button"
              onClick={handleStart}
              disabled={isSessionActive}
            >
              Start Session
            </button>

            <button
              type="button"
              onClick={handleStop}
              disabled={!isSessionActive}
            >
              Stop Session
            </button>
          </div>

          {isSessionActive && (
            <p role="status">Session started successfully</p>
          )}

          {!isSessionActive && (
            <p role="status">Session stopped successfully</p>
          )}
        </section>

        {/* Voice recording controls */}
        <section className="recording-section">
          <h2>Voice Recording Controls</h2>

          <p>
            Recording Status: <strong>{recordingStatus}</strong>
          </p>

          {recordingStatus === "recording" && (
            <p role="status">● Recording in progress</p>
          )}

          {recordingStatus === "paused" && (
            <p role="status">Recording paused</p>
          )}

          {recordingStatus === "stopped" && (
            <p role="status">Recording stopped</p>
          )}

          {isLoading && (
            <p role="status">Starting microphone...</p>
          )}

          <div className="session-buttons">
            <button
              type="button"
              onClick={handleStartRecording}
              disabled={
                isLoading ||
                recordingStatus === "recording" ||
                recordingStatus === "paused"
              }
            >
              Start Recording
            </button>

            <button
              type="button"
              onClick={handlePauseRecording}
              disabled={recordingStatus !== "recording"}
            >
              Pause Recording
            </button>

            <button
              type="button"
              onClick={handleResumeRecording}
              disabled={recordingStatus !== "paused"}
            >
              Resume Recording
            </button>

            <button
              type="button"
              onClick={handleStopRecording}
              disabled={
                recordingStatus !== "recording" &&
                recordingStatus !== "paused"
              }
            >
              Stop Recording
            </button>
          </div>

          {errorMessage && (
            <p role="alert">Error: {errorMessage}</p>
          )}
        </section>

        {/* Microphone selection */}
        <MicrophoneSelector />

        {/* Context and source panel */}
        <section className="context-section">
          <h2>Context / Source Panel</h2>

          <p className="context-description">
            Manage screen context and view the information sources
            used by the voice assistant.
          </p>

          <div className="context-toggle">
            <label htmlFor="screen-context">
              Enable Screen Context
            </label>

            <input
              id="screen-context"
              type="checkbox"
              checked={isScreenContextEnabled}
              onChange={(event) =>
                setIsScreenContextEnabled(event.target.checked)
              }
            />
          </div>

          <p
            className={
              isScreenContextEnabled
                ? "context-status enabled"
                : "context-status"
            }
            role="status"
          >
            Screen Context:{" "}
            {isScreenContextEnabled ? "ON" : "OFF"}
          </p>

          {!isScreenContextEnabled && (
            <p>
              Screen context is disabled. No screen content is being
              accessed.
            </p>
          )}

          {isScreenContextEnabled && (
            <>
              <p>
                Screen context is enabled. You can start screen
                sharing below when you are ready.
              </p>

              {/* Actual screen capture component */}
              <ScreenCapture />
            </>
          )}

          <div className="source-card">
            <h3>Available Sources</h3>

            <p>
              <strong>Source 1:</strong> Transcript messages
            </p>

            <p>
              <strong>Source 2:</strong> Microphone input
            </p>

            <p>
              <strong>Source 3:</strong>{" "}
              {isScreenContextEnabled
                ? "Screen context enabled (sharing requires your permission)"
                : "Screen context disabled"}
            </p>
          </div>
        </section>

        {/* Transcript timeline */}
        <section className="transcript-section">
          <h2>
            Transcript Timeline ({messages.length} messages)
          </h2>

          {messages.map((message) => (
            <article
              key={message.id}
              className="transcript-message"
            >
              <h3>{message.speaker}</h3>

              <p>{message.text}</p>

              <p>
                <strong>Time:</strong> {message.timestamp}
              </p>

              <p>
                <strong>Transcript Type:</strong>{" "}
                {message.type === "interim" ? "Interim" : "Final"}
              </p>

              <p>
                <strong>Confidence:</strong>{" "}
                {Math.round(message.confidence * 100)}%
              </p>

              <p>
                <strong>Revision:</strong> {message.revision}
              </p>

              {message.isRevised && (
                <p>
                  <strong>Revised Transcript</strong>
                </p>
              )}

              <hr />
            </article>
          ))}

          <button
            type="button"
            onClick={handleFinalizeTranscript}
            disabled={
              !messages.some((message) => message.type === "interim")
            }
          >
            Finalize Interim Transcript
          </button>

          <button
            type="button"
            onClick={handleAddMessage}
          >
            Add Transcript Message
          </button>
        </section>

      </main>

      <footer className="app-footer">
        <p>
          Academia AI Voice Co-Pilot | Development Mode
        </p>
      </footer>
    </div>
  );
}

export default App;
