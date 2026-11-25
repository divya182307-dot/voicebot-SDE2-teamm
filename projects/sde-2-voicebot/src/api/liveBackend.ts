import type { NewSessionEvent, SessionEvent } from "../types/session";

export type LiveEventHandler = (
  event: SessionEvent,
  delivery: { replayed: boolean },
) => void;

export class RealLiveBackend {
  private source: EventSource | null = null;
  private listeners = new Set<LiveEventHandler>();
  private lastEventId = 0;
  private connected = false;
  private sessionId: string;

  constructor(sessionId: string = '') {
    this.sessionId = sessionId;
  }

  setSessionId(sessionId: string): void {
    this.sessionId = sessionId
  }

  connect(): void {
    if (typeof EventSource === "undefined") {
      this.connected = false;
      return;
    }

    const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
    const url = `${baseUrl}/sessions/${encodeURIComponent(this.sessionId)}/events`

    if (!this.sessionId) {
      this.connected = false
      return
    }

    this.source = new EventSource(url)

    this.source.onopen = () => {
      this.connected = true
    }

    this.source.onmessage = (message) => {
      const event = JSON.parse(message.data) as SessionEvent
      const replayed = message.lastEventId
        ? Number(message.lastEventId) <= this.lastEventId
        : event.id <= this.lastEventId

      this.lastEventId = Math.max(this.lastEventId, event.id)
      for (const listener of this.listeners) {
        listener(event, { replayed })
      }
    }

    this.source.onerror = () => {
      this.connected = false
    }
  }

  disconnect(): void {
    this.source?.close()
    this.source = null
    this.connected = false
  }

  subscribe(handler: LiveEventHandler): () => void {
    this.listeners.add(handler)
    return () => this.listeners.delete(handler)
  }

  reconnect(): number {
    this.disconnect()
    this.connect()
    return 0
  }

  get isConnected(): boolean {
    return this.connected
  }
}

export class MockLiveBackend {
  private listeners = new Map<LiveEventHandler, number>();
  private events: SessionEvent[] = [];
  private connected = false;

  connect(): void {
    this.connected = true;
  }

  disconnect(): void {
    this.connected = false;
  }

  subscribe(handler: LiveEventHandler): () => void {
    this.listeners.set(handler, 0);

    return () => {
      this.listeners.delete(handler);
    };
  }

  publish(event: NewSessionEvent): void {
    const publishedEvent: SessionEvent = {
      ...event,
      id: this.events.length + 1,
    };

    this.events.push(publishedEvent);

    if (this.connected) {
      this.deliver(publishedEvent, false);
    }
  }

  reconnect(): number {
    this.connected = true;
    let replayedEvents = 0;

    for (const event of this.events) {
      if ([...this.listeners.values()].some((lastEventId) => event.id > lastEventId)) {
        replayedEvents += 1;
      }

      this.deliver(event, true);
    }

    return replayedEvents;
  }

  get isConnected(): boolean {
    return this.connected;
  }

  private deliver(event: SessionEvent, replayed: boolean): void {
    for (const [listener, lastEventId] of this.listeners) {
      if (event.id <= lastEventId) {
        continue;
      }

      listener(event, { replayed });
      this.listeners.set(listener, event.id);
    }
  }
}
