
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AudioLifecycle } from "./audioLifecycle";

describe("AudioLifecycle", () => {
  let audio: AudioLifecycle;
  let mockTrack: { stop: ReturnType<typeof vi.fn> };
  let mockStream: {
    getTracks: ReturnType<typeof vi.fn>;
  };
  let mockRecorder: {
    start: ReturnType<typeof vi.fn>;
    pause: ReturnType<typeof vi.fn>;
    resume: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    state: "inactive" | "recording" | "paused";
    ondataavailable: ((event: BlobEvent) => void) | null;
  };

  beforeEach(() => {
    audio = new AudioLifecycle();

    mockTrack = {
      stop: vi.fn(),
    };

    mockStream = {
      getTracks: vi.fn(() => [mockTrack]),
    };

    mockRecorder = {
      start: vi.fn(function (this: typeof mockRecorder) {
        this.state = "recording";
      }),
      pause: vi.fn(function (this: typeof mockRecorder) {
        this.state = "paused";
      }),
      resume: vi.fn(function (this: typeof mockRecorder) {
        this.state = "recording";
      }),
      stop: vi.fn(function (this: typeof mockRecorder) {
        this.state = "inactive";
      }),
      state: "inactive",
      ondataavailable: null,
    };

    vi.stubGlobal("MediaRecorder", vi.fn(function () {
      return mockRecorder;
    }));

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue(mockStream),
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("should start with idle status", () => {
    expect(audio.status).toBe("idle");
  });

  it("should return empty audio chunks initially", () => {
    expect(audio.getAudioChunks()).toEqual([]);
  });

  it("should stop safely before recording starts", () => {
    audio.stop();
    expect(audio.status).toBe("stopped");
  });

  it("should start recording successfully", async () => {
    await audio.start();

    expect(audio.status).toBe("recording");
    expect(mockRecorder.start).toHaveBeenCalled();
  });

  it("should pause recording successfully", async () => {
    await audio.start();

    audio.pause();

    expect(audio.status).toBe("paused");
    expect(mockRecorder.pause).toHaveBeenCalled();
  });

  it("should resume paused recording successfully", async () => {
    await audio.start();

    audio.pause();
    audio.resume();

    expect(audio.status).toBe("recording");
    expect(mockRecorder.resume).toHaveBeenCalled();
  });

  it("should stop active recording and release microphone tracks", async () => {
    await audio.start();

    audio.stop();

    expect(audio.status).toBe("stopped");
    expect(mockRecorder.stop).toHaveBeenCalled();
    expect(mockTrack.stop).toHaveBeenCalled();
  });

  it("should not start duplicate recording", async () => {
    await audio.start();

    const getUserMedia = navigator.mediaDevices.getUserMedia;

    await audio.start();

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(mockRecorder.start).toHaveBeenCalledTimes(1);
  });

  it("should handle microphone permission errors", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(
      new Error("Microphone permission denied")
    );

    await expect(audio.start()).rejects.toThrow(
      "Microphone permission denied"
    );

    expect(audio.status).toBe("idle");
  });

  it("should collect audio chunks when data is available", async () => {
    await audio.start();

    const audioBlob = new Blob(["test audio"], { type: "audio/webm" });

    mockRecorder.ondataavailable?.({
      data: audioBlob,
    } as BlobEvent);

    expect(audio.getAudioChunks()).toHaveLength(1);
    expect(audio.getAudioChunks()[0]).toBe(audioBlob);
  });

  it("should not pause when recording is not active", () => {
    audio.pause();

    expect(audio.status).toBe("idle");
    expect(mockRecorder.pause).not.toHaveBeenCalled();
  });

  it("should not resume when recording is not paused", () => {
    audio.resume();

    expect(audio.status).toBe("idle");
    expect(mockRecorder.resume).not.toHaveBeenCalled();
  });
});
