
import { useEffect, useState } from "react";
import {
  getAudioInputDevices,
  requestMicrophonePermission,
  stopMicrophone,
  type AudioInputDevice,
} from "../audio/deviceAdapter";

export default function MicrophoneSelector() {
  const [devices, setDevices] = useState<AudioInputDevice[]>([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [status, setStatus] = useState("Not requested");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function loadDevices() {
      try {
        const availableDevices = await getAudioInputDevices();

        if (mounted) {
          setDevices(availableDevices);
          setSelectedDevice(
            availableDevices[0]?.deviceId ?? ""
          );
        }
      } catch (error) {
        if (mounted) {
          setMessage(
            error instanceof Error
              ? error.message
              : "Unable to load microphones."
          );
        }
      }
    }

    void loadDevices();

    return () => {
      mounted = false;
    };
  }, []);

  async function handlePermissionRequest() {
    setLoading(true);
    setMessage("");

    try {
      const stream = await requestMicrophonePermission(
        selectedDevice || undefined
      );

      setStatus("Permission Granted");
      setMessage("Microphone access is ready.");

      // Release the microphone immediately.
      stopMicrophone(stream);

      const availableDevices = await getAudioInputDevices();
      setDevices(availableDevices);
    } catch (error) {
      setStatus("Permission Denied or Unavailable");
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to access microphone."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="microphone-selector">
      <h2>Microphone Device Selection</h2>

      <label htmlFor="microphone-device">
        Select Microphone
      </label>

      <select
        id="microphone-device"
        value={selectedDevice}
        onChange={(event) =>
          setSelectedDevice(event.target.value)
        }
      >
        {devices.length === 0 && (
          <option value="">No microphones found</option>
        )}

        {devices.map((device) => (
          <option
            key={device.deviceId}
            value={device.deviceId}
          >
            {device.label}
            {device.isDefault ? " (Default)" : ""}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={handlePermissionRequest}
        disabled={loading}
      >
        {loading
          ? "Requesting Permission..."
          : "Request Microphone Permission"}
      </button>

      <p>
        <strong>Microphone Status:</strong> {status}
      </p>

      {message && <p role="status">{message}</p>}
    </section>
  );
}
