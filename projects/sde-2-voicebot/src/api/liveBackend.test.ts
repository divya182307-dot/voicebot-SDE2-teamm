import { describe, expect, it, vi } from "vitest";
import { MockLiveBackend, RealLiveBackend } from "./liveBackend";
import type { NewSessionEvent, SessionEvent, WorkflowStep } from "../types/session";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  listeners = new Map<string, EventListener>();
  close = vi.fn();
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  emit(event: SessionEvent): void {
    this.onmessage?.({
      data: JSON.stringify(event),
      lastEventId: String(event.id),
    } as MessageEvent);
  }

  addEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, listener);
  }

  emitNamed(type: string): void {
    this.listeners.get(type)?.(new Event(type));
  }
}

describe("MockLiveBackend", () => {
  it("publishes events while connected", () => {
    const backend = new MockLiveBackend();
    const handler = vi.fn();
    backend.connect();
    backend.subscribe(handler);

    backend.publish({
      type: "workflow",
      payload: [{ id: "audio", label: "Capture audio", status: "complete" }],
    });

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("buffers events while disconnected and replays them on reconnect", async () => {
    vi.useFakeTimers();
    const backend = new MockLiveBackend();
    const handler = vi.fn();

    backend.connect();
    backend.subscribe(handler);
    backend.disconnect();

    const missedEvent: NewSessionEvent = {
      type: "approval",
      payload: {
        message: "Approval requested",
        action: "Execute the pending action",
        reason: "This action changes external state.",
        screenContextEnabled: false,
      },
    };
    backend.publish(missedEvent);

    expect(handler).not.toHaveBeenCalled();

    expect(backend.reconnect()).toBe(1);
    await vi.runAllTimersAsync();

    expect(handler).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("replays only missed events and never redelivers acknowledged events", async () => {
    vi.useFakeTimers();
    const backend = new MockLiveBackend();
    const handler = vi.fn();

    backend.connect();
    backend.subscribe(handler);

    const payload: WorkflowStep[] = [
      { id: "audio", label: "Capture audio", status: "complete" },
    ];
    backend.publish({ type: "workflow", payload });

    backend.disconnect();
    backend.publish({
      type: "approval",
      payload: {
        message: "Approval requested",
        action: "Execute the pending action",
        reason: "This action changes external state.",
        screenContextEnabled: false,
      },
    });

    expect(backend.reconnect()).toBe(1);
    await vi.runAllTimersAsync();
    expect(backend.reconnect()).toBe(0);

    expect(handler).toHaveBeenCalledTimes(2);
    expect(new Set(handler.mock.calls.map(([event]) => event.id)).size).toBe(2);
    vi.useRealTimers();
  });
});

describe("RealLiveBackend", () => {
  it("reconnects to the session stream and drops duplicate event IDs", () => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);

    const backend = new RealLiveBackend("session/1");
    const handler = vi.fn();
    const statuses: string[] = [];
    backend.subscribe(handler);
    backend.subscribeStatus((status) => statuses.push(status));
    backend.connect();

    const firstSource = FakeEventSource.instances[0];
    expect(firstSource.url).toContain("/sessions/session%2F1/events");
    firstSource.onopen?.(new Event("open"));
    firstSource.emit({
      id: 1,
      type: "workflow",
      payload: [{ id: "audio", label: "Capture audio", status: "active" }],
    });

    firstSource.onerror?.(new Event("error"));
    backend.reconnect();
    const replaySource = FakeEventSource.instances[1];
    replaySource.onopen?.(new Event("open"));
    replaySource.emit({
      id: 1,
      type: "workflow",
      payload: [{ id: "audio", label: "Capture audio", status: "active" }],
    });
    replaySource.emit({
      id: 2,
      type: "workflow",
      payload: [{ id: "audio", label: "Capture audio", status: "complete" }],
    });
    replaySource.emitNamed("replay-complete");
    replaySource.emit({
      id: 3,
      type: "workflow",
      payload: [{ id: "audio", label: "Capture audio", status: "complete" }],
    });

    expect(handler).toHaveBeenCalledTimes(3);
    expect(handler.mock.calls[1][0].id).toBe(2);
    expect(handler.mock.calls[1][1].replayed).toBe(true);
    expect(handler.mock.calls[2][1].replayed).toBe(false);
    expect(statuses).toContain("reconnecting");
    expect(statuses.at(-1)).toBe("connected");
    expect(firstSource.close).toHaveBeenCalledOnce();

    backend.setSessionId("new-session");
    backend.reconnect();
    expect(FakeEventSource.instances[2].url).not.toContain("?after=");

    backend.disconnect();
    vi.unstubAllGlobals();
  });
});
