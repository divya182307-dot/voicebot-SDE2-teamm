import { describe, expect, it, vi } from "vitest";
import { MockLiveBackend } from "./liveBackend";
import type { NewSessionEvent, WorkflowStep } from "../types/session";

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
