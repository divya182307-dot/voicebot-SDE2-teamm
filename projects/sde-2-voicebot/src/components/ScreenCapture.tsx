
import { useEffect, useRef, useState } from "react";

function ScreenCapture() {
  const [isCapturing, setIsCapturing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const startScreenCapture = async () => {
    setErrorMessage("");

    try {
      if (!navigator.mediaDevices?.getDisplayMedia) {
        throw new Error("Screen capture is not supported in this browser.");
      }

      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      });

      streamRef.current = stream;
      setIsCapturing(true);

      stream.getVideoTracks()[0]?.addEventListener(
        "ended",
        () => {
          streamRef.current = null;
          setIsCapturing(false);
        },
        { once: true }
      );
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Unable to capture screen."
      );
    }
  };

  const stopScreenCapture = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setIsCapturing(false);
  };

  useEffect(() => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [isCapturing]);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return (
    <section className="context-section">
      <h2>Screen Capture</h2>
      <p>Share your screen only when you choose to give permission.</p>

      <p role="status">
        Screen Capture Status:{" "}
        <strong>{isCapturing ? "Active" : "OFF"}</strong>
      </p>

      {!isCapturing ? (
        <button type="button" onClick={startScreenCapture}>
          Start Screen Capture
        </button>
      ) : (
        <button type="button" onClick={stopScreenCapture}>
          Stop Screen Capture
        </button>
      )}

      {errorMessage && <p role="alert">{errorMessage}</p>}

      {isCapturing && (
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          style={{
            width: "100%",
            maxWidth: "600px",
            marginTop: "15px",
            borderRadius: "8px",
          }}
        />
      )}
    </section>
  );
}

export default ScreenCapture;
