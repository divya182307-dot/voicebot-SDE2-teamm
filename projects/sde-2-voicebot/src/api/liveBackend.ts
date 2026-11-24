import type { NewSessionEvent, SessionEvent } from "../types/session";

export type LiveEventHandler = (
  event: SessionEvent,
  delivery: { replayed: boolean },
) => void;

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
