
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import ScreenCapture from "./ScreenCapture";

describe("ScreenCapture Component", () => {
  let mockTrack: {
    stop: ReturnType<typeof vi.fn>;
    addEventListener: ReturnType<typeof vi.fn>;
  };

  let mockStream: {
    getTracks: ReturnType<typeof vi.fn>;
    getVideoTracks: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    mockTrack = {
      stop: vi.fn(),
      addEventListener: vi.fn(),
    };

    mockStream = {
      getTracks: vi.fn(() => [mockTrack]),
      getVideoTracks: vi.fn(() => [mockTrack]),
    };

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getDisplayMedia: vi.fn().mockResolvedValue(mockStream),
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("should display screen capture as OFF initially", () => {
    render(<ScreenCapture />);

    expect(screen.getByText("Screen Capture Status:")).toBeInTheDocument();
    expect(screen.getByText("OFF")).toBeInTheDocument();
  });

  it("should start screen capture successfully", async () => {
    render(<ScreenCapture />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Start Screen Capture",
      }));
    });

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Stop Screen Capture",
    })).toBeInTheDocument();
  });

  it("should display the screen preview when capture starts", async () => {
    render(<ScreenCapture />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Start Screen Capture",
      }));
    });

    expect(document.querySelector("video")).toBeInTheDocument();
  });

  it("should stop screen capture successfully", async () => {
    render(<ScreenCapture />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Start Screen Capture",
      }));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Stop Screen Capture",
      }));
    });

    expect(screen.getByText("OFF")).toBeInTheDocument();
    expect(mockTrack.stop).toHaveBeenCalled();
    expect(document.querySelector("video")).not.toBeInTheDocument();
  });

  it("should handle screen capture permission denial", async () => {
    vi.mocked(navigator.mediaDevices.getDisplayMedia).mockRejectedValueOnce(
      new Error("Permission denied")
    );

    render(<ScreenCapture />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Start Screen Capture",
      }));
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Permission denied");
    expect(screen.getByText("OFF")).toBeInTheDocument();
  });

  it("should clean up screen sharing when component unmounts", async () => {
    const { unmount } = render(<ScreenCapture />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Start Screen Capture",
      }));
    });

    unmount();

    expect(mockTrack.stop).toHaveBeenCalled();
  });

  it("should stop capture when the browser sharing track ends", async () => {
    render(<ScreenCapture />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", {
        name: "Start Screen Capture",
      }));
    });

    const endedCallback = mockTrack.addEventListener.mock.calls.find(
      (call) => call[0] === "ended"
    )?.[1];

    expect(endedCallback).toBeDefined();

    act(() => {
      endedCallback();
    });

    expect(screen.getByText("OFF")).toBeInTheDocument();
  });
});
