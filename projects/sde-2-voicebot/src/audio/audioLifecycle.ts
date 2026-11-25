
export type AudioStatus = "idle" | "recording" | "paused" | "stopped";

export class AudioLifecycle {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  public status: AudioStatus = "idle";

  async start(deviceId?: string): Promise<void> {
    if (this.status === "recording" || this.status === "paused") {
      return;
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
      video: false,
    });

    this.chunks = [];

    this.recorder = new MediaRecorder(this.stream);

    this.recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) {
        this.chunks.push(event.data);
      }
    };

    this.recorder.start();
    this.status = "recording";
  }

  pause(): void {
    if (this.recorder?.state === "recording") {
      this.recorder.pause();
      this.status = "paused";
    }
  }

  resume(): void {
    if (this.recorder?.state === "paused") {
      this.recorder.resume();
      this.status = "recording";
    }
  }

  stop(): void {
    if (this.recorder && this.recorder.state !== "inactive") {
      this.recorder.stop();
    }

    this.stream?.getTracks().forEach((track) => track.stop());

    this.stream = null;
    this.status = "stopped";
  }

  getAudioChunks(): Blob[] {
    return [...this.chunks];
  }
}
