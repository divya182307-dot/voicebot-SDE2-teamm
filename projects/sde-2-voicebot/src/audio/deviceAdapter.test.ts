import { describe, it, expect } from "vitest";
import { AudioLifecycle } from "./audioLifecycle";

describe("Audio Lifecycle", () => {
  it("should start with idle status", () => {
    const audio = new AudioLifecycle();
    expect(audio.status).toBe("idle");
  });

  it("should return empty audio chunks initially", () => {
    const audio = new AudioLifecycle();
    expect(audio.getAudioChunks()).toEqual([]);
  });

  it("should stop safely before recording starts", () => {
    const audio = new AudioLifecycle();
    audio.stop();
    expect(audio.status).toBe("stopped");
  });
});