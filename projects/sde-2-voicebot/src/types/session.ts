
export interface Session {
  sessionId: string;
  status: "active" | "stopped";
  message: string;
}

export interface ApiError {
  message: string;
  statusCode?: number;
}

export interface TranscriptMessage {
  id: number;
  speaker: "Student" | "AI Assistant";
  text: string;
  timestamp: string;

  // Transcript status
  type: "interim" | "final";

  // Speech recognition confidence score
  confidence: number;

  // Revision tracking
  revision: number;
  isRevised: boolean;
}

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: ApiError;
}

export type WorkflowStepStatus = "pending" | "active" | "complete" | "rejected";

export interface WorkflowStep {
  id: string;
  label: string;
  status: WorkflowStepStatus;
}

export type LiveConnectionStatus = "connected" | "disconnected" | "reconnecting";

export type SessionEvent =
  | {
      id: number;
      type: "session";
      payload: Pick<Session, "sessionId" | "status">;
    }
  | { id: number; type: "workflow"; payload: WorkflowStep[] }
  | { id: number; type: "transcript"; payload: TranscriptMessage }
  | {
      id: number;
      type: "approval";
      payload: { message: string; screenContextEnabled: boolean };
    }
  | {
      id: number;
      type: "approval-decision";
      payload: { decision: "approved" | "rejected" };
    }
  | { id: number; type: "execution"; payload: { message: string } };

export type NewSessionEvent = SessionEvent extends infer Event
  ? Event extends SessionEvent
    ? Omit<Event, "id">
    : never
  : never;
