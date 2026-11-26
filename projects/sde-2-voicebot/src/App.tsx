
import { useEffect, useRef, useState } from "react";
import MicrophoneSelector from "./components/MicrophoneSelector";
import ScreenCapture from "./components/ScreenCapture";
import {
  AudioLifecycle,
  type AudioStatus,
} from "./audio/audioLifecycle";
import type {
  LiveConnectionStatus,
  TranscriptMessage,
  WorkflowStep,
} from "./types/session";
import { mockTranscript } from "./fixtures/transcript";
import { MockLiveBackend, RealLiveBackend } from "./api/liveBackend";
import {
  approveAction,
  publishSessionEvent,
  rejectAction,
  startSession,
  stopSession,
} from "./api/api";
import "./App.css";

function App() {
  const isDemoMode =
    import.meta.env.MODE === "test" ||
    new URLSearchParams(window.location.search).get("demo") === "1";
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

  const [liveConnectionStatus, setLiveConnectionStatus] =
    useState<LiveConnectionStatus>(
      isDemoMode ? "connected" : "disconnected"
    );
  const [workflowSteps, setWorkflowSteps] = useState<WorkflowStep[]>([
    { id: "audio", label: "Capture audio", status: "pending" },
    { id: "transcript", label: "Build transcript", status: "pending" },
    { id: "reasoning", label: "Generate assistant response", status: "pending" },
    { id: "approval", label: "Approval review", status: "pending" },
  ]);
  const [isApprovalOpen, setIsApprovalOpen] = useState(false);
  const [approvalDecision, setApprovalDecision] = useState("");
  const [approvalScreenContextEnabled, setApprovalScreenContextEnabled] =
    useState(false);
  const [approvalAction, setApprovalAction] = useState("execute the pending workflow action");
  const [approvalReason, setApprovalReason] = useState(
    "The action requires your explicit permission before execution."
  );
  const [executionCount, setExecutionCount] = useState(0);
  const [replayedEventCount, setReplayedEventCount] = useState(0);
  const [lastEventId, setLastEventId] = useState(0);
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<TranscriptMessage[]>([
    ...(isDemoMode
      ? [mockTranscript[0], mockTranscript[1], mockTranscript[2], mockTranscript[4]]
      : []),
  ]);

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

  useEffect(() => {
    if (!isApprovalOpen) {
      return;
    }

    const dialog = approvalDialogRef.current;
    const previousFocus = document.activeElement as HTMLElement | null;
    const focusableElements = () =>
      dialog?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );

    focusableElements()?.[0]?.focus();

    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsApprovalOpen(false);
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusable = focusableElements();
      if (!focusable?.length) {
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleDialogKeyDown);

    return () => {
      document.removeEventListener("keydown", handleDialogKeyDown);
      if (previousFocus?.isConnected) {
        previousFocus.focus();
      }
    };
  }, [isApprovalOpen]);

  const audioLifecycle = useRef<AudioLifecycle | null>(null);
  const liveBackend = useRef<MockLiveBackend | RealLiveBackend | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const recordingStartVersion = useRef(0);
  const approvalDialogRef = useRef<HTMLElement | null>(null);

  if (liveBackend.current === null) {
    liveBackend.current = isDemoMode
      ? new MockLiveBackend()
      : new RealLiveBackend();
  }

  useEffect(() => {
    const backend = liveBackend.current!;
    if (backend instanceof MockLiveBackend) {
      backend.connect();
    }

    const unsubscribe = backend.subscribe((event, delivery) => {
      if (event.type === "session") {
        setIsSessionActive(event.payload.status === "active");
        setSessionId(event.payload.sessionId);
      }

      setLastEventId(event.id);

      if (event.type === "workflow") {
        setWorkflowSteps(event.payload);
      } else if (event.type === "transcript") {
        setMessages((previousMessages) =>
          previousMessages.some((message) => message.id === event.payload.id)
            ? previousMessages
            : [...previousMessages, event.payload]
        );
      } else if (event.type === "approval") {
        setApprovalScreenContextEnabled(event.payload.screenContextEnabled);
        setApprovalAction(event.payload.action || event.payload.message);
        setApprovalReason(
          event.payload.reason || "This action requires your explicit approval."
        );
        setIsApprovalOpen(true);
      } else if (event.type === "approval-decision") {
        setApprovalDecision(
          event.payload.decision === "approved"
            ? "Approved"
            : "Rejected: execution was not started"
        );
        setIsApprovalOpen(false);
      } else if (event.type === "execution") {
        setExecutionCount((count) => count + 1);
      }

      if (delivery.replayed) {
        setReplayedEventCount((count) => count + 1);
      }
    });
    const unsubscribeStatus =
      backend instanceof RealLiveBackend
        ? backend.subscribeStatus(setLiveConnectionStatus)
        : () => {};

    return () => {
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
      }
      unsubscribe();
      unsubscribeStatus();
      backend.disconnect();
    };
  }, []);

  if (audioLifecycle.current === null) {
    audioLifecycle.current = new AudioLifecycle();
  }

  const publishWorkflow = async (steps: WorkflowStep[], targetSessionId = sessionId) => {
    if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish({ type: "workflow", payload: steps });
      return;
    }

    if (targetSessionId) {
      const response = await publishSessionEvent(targetSessionId, {
        type: "workflow",
        payload: steps,
      });
      if (!response.success) {
        setErrorMessage(response.error?.message || "Unable to update workflow.");
      }
    }
  };

  // Demo mode and tests use the in-memory backend; normal app mode uses HTTP/SSE.
  const handleStart = async () => {
    setIsLoading(true);
    setErrorMessage("");

    if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish({
        type: "session",
        payload: { sessionId: "mock-session-001", status: "active" },
      });
      setIsLoading(false);
      await publishWorkflow([
        { id: "audio", label: "Capture audio", status: "active" },
        { id: "transcript", label: "Build transcript", status: "pending" },
        { id: "reasoning", label: "Generate assistant response", status: "pending" },
        { id: "approval", label: "Approval review", status: "pending" },
      ]);
      return;
    }

    const response = await startSession();
    if (!response.success || !response.data) {
      setErrorMessage(response.error?.message || "Unable to start session.");
      setIsLoading(false);
      return;
    }

    if (liveBackend.current instanceof RealLiveBackend) {
      setSessionId(response.data.sessionId);
      liveBackend.current.setSessionId(response.data.sessionId);
      liveBackend.current.connect();
    }

    await publishWorkflow([
      { id: "audio", label: "Capture audio", status: "active" },
      { id: "transcript", label: "Build transcript", status: "pending" },
      { id: "reasoning", label: "Generate assistant response", status: "pending" },
      { id: "approval", label: "Approval review", status: "pending" },
    ], response.data.sessionId);
    setIsLoading(false);
  };

  // Stop recording and the backend session.
  const handleStop = async () => {
    recordingStartVersion.current += 1;

    if (recordingStatus === "recording" || recordingStatus === "paused") {
      audioLifecycle.current!.stop();
      setRecordingStatus("stopped");
    }

    setIsLoading(true);
    setErrorMessage("");

    if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish({
        type: "session",
        payload: {
          sessionId: sessionId || "mock-session-001",
          status: "stopped",
        },
      });
      setIsSessionActive(false);
      setIsLoading(false);
      return;
    }

    const response = await stopSession(sessionId);
    setIsLoading(false);

    if (!response.success) {
      setErrorMessage(response.error?.message || "Unable to stop session.");
      return;
    }

    setIsSessionActive(false);
    liveBackend.current?.disconnect();
    setLiveConnectionStatus("disconnected");
  };

  // Start recording.
  const handleStartRecording = async () => {
    const startVersion = recordingStartVersion.current;
    setIsLoading(true);
    setErrorMessage("");

    try {
      await audioLifecycle.current!.start();

      if (startVersion !== recordingStartVersion.current) {
        audioLifecycle.current!.stop();
        setRecordingStatus("stopped");
        return;
      }

      setRecordingStatus("recording");
      const currentSteps = workflowSteps;
      if (isSessionActive && currentSteps[0]?.status === "active") {
        await publishWorkflow([
          { ...currentSteps[0], status: "complete" },
          { ...currentSteps[1], status: "active" },
          ...currentSteps.slice(2),
        ]);
      }
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

  const handleDisconnectLiveBackend = () => {
    liveBackend.current!.disconnect();
    setLiveConnectionStatus("disconnected");
  };

  const handleReconnectLiveBackend = () => {
    if (liveBackend.current instanceof RealLiveBackend) {
      liveBackend.current.reconnect();
      return;
    }

    setLiveConnectionStatus("reconnecting");

    reconnectTimer.current = window.setTimeout(() => {
      const replayed = liveBackend.current!.reconnect();
      setReplayedEventCount(replayed);
      setLiveConnectionStatus("connected");
      reconnectTimer.current = null;
    }, 300);
  };

  const handleAdvanceWorkflow = async () => {
    const activeIndex = workflowSteps.findIndex(
      (step) => step.status === "active"
    );

    if (
      activeIndex === -1 ||
      workflowSteps[activeIndex]?.id === "approval"
    ) {
      return;
    }

    const updatedSteps = workflowSteps.map((step, index) => {
      if (index < activeIndex) {
        return { ...step, status: "complete" as const };
      }

      if (index === activeIndex) {
        return { ...step, status: "complete" as const };
      }

      if (index === activeIndex + 1) {
        return { ...step, status: "active" as const };
      }

      return step;
    });

    await publishWorkflow(updatedSteps);
  };

  const handleOpenApproval = async () => {
    if (!workflowSteps.some((step) => step.id === "approval" && step.status === "active")) {
      return;
    }

    setApprovalDecision("");
    const approvalEvent = {
      type: "approval" as const,
      payload: {
        message: "The assistant is requesting permission to save a study plan.",
        action: "Save a study plan generated from this session's transcript",
        reason: "Saving creates persistent study-plan content from your transcript, so review it before it is added to your account.",
        screenContextEnabled: isScreenContextEnabled,
      },
    };

    if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish(approvalEvent);
    } else if (sessionId) {
      const response = await publishSessionEvent(sessionId, approvalEvent);
      if (!response.success) {
        setErrorMessage(response.error?.message || "Unable to request approval.");
      }
    } else {
      setErrorMessage("Start a session before requesting approval.");
    }
  };

  const handleApprove = async () => {
    if (liveBackend.current instanceof RealLiveBackend && sessionId) {
      setIsLoading(true);
      const response = await approveAction(sessionId);
      setIsLoading(false);
      if (!response.success) {
        setErrorMessage(response.error?.message || "Unable to approve action.");
        return;
      }
      setApprovalDecision("Approved");
      setIsApprovalOpen(false);
    } else if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish({
        type: "execution",
        payload: { message: "Approved action execution started." },
      });
      liveBackend.current.publish({
        type: "approval-decision",
        payload: { decision: "approved" },
      });
    }
    await publishWorkflow(
      workflowSteps.map((step) =>
        step.status === "pending" || step.status === "active"
          ? { ...step, status: "complete" as const }
          : step
      )
    );
  };

  const handleReject = async () => {
    if (liveBackend.current instanceof RealLiveBackend && sessionId) {
      setIsLoading(true);
      const response = await rejectAction(sessionId);
      setIsLoading(false);
      if (!response.success) {
        setErrorMessage(response.error?.message || "Unable to reject action.");
        return;
      }
      setApprovalDecision("Rejected: execution was not started");
      setIsApprovalOpen(false);
    } else if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish({
        type: "approval-decision",
        payload: { decision: "rejected" },
      });
    }
    await publishWorkflow(
      workflowSteps.map((step) =>
        step.status === "active" || step.status === "pending"
          ? { ...step, status: "rejected" as const }
          : step
      )
    );
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

    if (liveBackend.current instanceof MockLiveBackend) {
      liveBackend.current.publish({
        type: "transcript",
        payload: newMessage,
      });
    } else if (sessionId) {
      void publishSessionEvent(sessionId, {
        type: "transcript",
        payload: newMessage,
      }).then((response) => {
        if (!response.success) {
          setErrorMessage(response.error?.message || "Unable to publish transcript.");
        }
      });
    }
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
        {isDemoMode ? (
          <a className="demo-link" href="/">
            Return to live mode
          </a>
        ) : (
          <a className="demo-link" href="?demo=1">
            Try demo mode
          </a>
        )}
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

        {/* Backend mode */}
        <div className="mock-banner">
          <strong>
            {isDemoMode
              ? "Demo Mode: Mock Session and Event Stream"
              : "Live Backend API and Event Stream"}
          </strong>
          <p>
            {isDemoMode
              ? "The complete workflow runs on sample data without a backend or API keys."
              : "Session, workflow, approval, and transcript updates use the configured backend."}
          </p>
        </div>

        {/* Session controls */}
        <section className="session-section">
          <h2>Session Controls</h2>

          <p role="status" aria-live="polite" aria-atomic="true">
            Session Status:{" "}
            {isSessionActive ? "active" : "stopped"}
          </p>
          {sessionId && <p>Session ID: {sessionId}</p>}

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

          {isSessionActive && <p role="status">Session started successfully</p>}
          {!isSessionActive && <p role="status">Session stopped successfully</p>}
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

        {/* Live backend connection */}
        <section className="live-section">
          <h2>Live Backend Connection</h2>
          <p>
            <span>{`Live Connection Status: ${liveConnectionStatus}`}</span>
          </p>
          <p>Last event received: {lastEventId || "none"}</p>

          {liveConnectionStatus === "reconnecting" && (
            <p role="status">Reconnecting and replaying missed events...</p>
          )}

          {liveConnectionStatus === "disconnected" && (
            <p role="status">The live backend is disconnected.</p>
          )}

          {replayedEventCount > 0 && liveConnectionStatus === "connected" && (
            <p role="status">
              Replayed {replayedEventCount} missed event{replayedEventCount === 1 ? "" : "s"}.
            </p>
          )}

          <div className="session-buttons">
            <button
              type="button"
              onClick={handleReconnectLiveBackend}
              disabled={liveConnectionStatus === "connected"}
            >
              Reconnect
            </button>
            <button
              type="button"
              onClick={handleDisconnectLiveBackend}
              disabled={liveConnectionStatus !== "connected"}
            >
              Disconnect
            </button>
          </div>
        </section>

        {/* Workflow progress */}
        <section className="workflow-section">
          <h2>Workflow Progress</h2>
          <ol
            className="workflow-list"
            aria-label="Workflow step statuses"
            aria-live="polite"
            aria-relevant="additions text"
          >
            {workflowSteps.map((step) => (
              <li key={step.id}>
                <span>{step.label}</span>
                <strong className={`workflow-status ${step.status}`}>
                  {step.status}
                </strong>
              </li>
            ))}
          </ol>
          {approvalDecision && (
            <p role="status">Approval Decision: {approvalDecision}</p>
          )}
          <div className="session-buttons">
            <button
              type="button"
              onClick={handleAdvanceWorkflow}
              disabled={
                !workflowSteps.some(
                  (step) => step.status === "active" && step.id !== "approval"
                )
              }
            >
              Advance Workflow
            </button>
            <button
              type="button"
              onClick={handleOpenApproval}
              disabled={
                !workflowSteps.some(
                  (step) => step.id === "approval" && step.status === "active"
                ) || isApprovalOpen
              }
            >
              Open Approval Dialog
            </button>
          </div>
          <p role="status">Actions executed: {executionCount}</p>
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

        {/* Privacy settings */}
        <section className="privacy-section">
          <h2>Privacy Settings</h2>
          <p>
            <span>{`Screen context is ${isScreenContextEnabled ? "ON" : "OFF"}.`}</span>
            {" "}Screen content is only considered when enabled and explicitly shared.
          </p>
          <label htmlFor="screen-context">
            <input
              id="screen-context"
              type="checkbox"
              checked={isScreenContextEnabled}
              onChange={(event) =>
                setIsScreenContextEnabled(event.target.checked)
              }
            />
            Enable Screen Context
          </label>
        </section>

        {/* Transcript timeline */}
        <section className="transcript-section">
          <h2>
            Transcript Timeline ({messages.length} messages)
          </h2>

          <div
            className="transcript-list"
            aria-label="Transcript messages"
            aria-live="polite"
            aria-relevant="additions text"
          >
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
          </div>

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

        {isApprovalOpen && (
          <div
            className="approval-overlay"
            role="presentation"
          >
            <section
              className="approval-dialog"
              ref={approvalDialogRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="approval-title"
              aria-describedby="approval-details approval-reason approval-risk"
            >
              <h2 id="approval-title">Approve or Reject Action</h2>
              <p id="approval-details">
                <strong>Action:</strong> {approvalAction}
              </p>
              <p id="approval-reason">
                <strong>Why approval is required:</strong> {approvalReason}
              </p>
              <p id="approval-risk">
                <strong>Risk if approved:</strong> The assistant will perform
                this action: {approvalAction}, using the transcript
                {approvalScreenContextEnabled
                  ? " and screen context you explicitly shared."
                  : ". Screen context is disabled and will not be used."}
              </p>
              <p>
                Rejecting records the decision and prevents execution.
              </p>
              <p>
                Screen context for this action:{" "}
                <strong>{approvalScreenContextEnabled ? "ON" : "OFF"}</strong>
              </p>

              <div className="session-buttons">
                <button type="button" onClick={handleApprove} disabled={isLoading}>
                  Approve
                </button>
                <button type="button" onClick={handleReject} disabled={isLoading}>
                  Reject
                </button>
              </div>
            </section>
          </div>
        )}

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
