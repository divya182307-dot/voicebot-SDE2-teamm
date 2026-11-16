export interface AudioInputDevice {
  deviceId: string;
  label: string;
  isDefault: boolean;
}

export type MicrophonePermissionStatus =
  | "granted"
  | "denied"
  | "prompt"
  | "unsupported"
  | "error";

export interface MicrophonePermissionResult {
  status: MicrophonePermissionStatus;
  message: string;
}

const isMicrophoneSupported = (): boolean => {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function"
  );
};

/**
 * Get the list of available microphone devices.
 */
export async function getAudioInputDevices(): Promise<AudioInputDevice[]> {
  if (!isMicrophoneSupported()) {
    throw new Error("Microphone devices are not supported in this browser.");
  }

  const devices = await navigator.mediaDevices.enumerateDevices();

  return devices
    .filter((device) => device.kind === "audioinput")
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label || `Microphone ${index + 1}`,
      isDefault: device.deviceId === "default",
    }));
}

/**
 * Request microphone permission for the selected device.
 */
export async function requestMicrophonePermission(
  deviceId?: string,
): Promise<MediaStream> {
  if (!isMicrophoneSupported()) {
    throw new Error("Your browser does not support microphone access.");
  }

  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: deviceId
        ? {
            deviceId: { exact: deviceId },
          }
        : true,
      video: false,
    });
  } catch (error) {
    if (error instanceof Error) {
      switch (error.name) {
        case "NotAllowedError":
        case "PermissionDeniedError":
          throw new Error("Microphone permission was denied.");

        case "NotFoundError":
        case "DevicesNotFoundError":
          throw new Error("No microphone device was found.");

        case "NotReadableError":
        case "TrackStartError":
          throw new Error("Microphone is being used by another application.");

        case "OverconstrainedError":
          throw new Error("The selected microphone is not available.");

        case "SecurityError":
          throw new Error("Microphone access requires a secure connection.");

        default:
          throw new Error(`Microphone error: ${error.message}`);
      }
    }

    throw new Error("An unexpected microphone error occurred.");
  }
}

/**
 * Check the current microphone permission status.
 */
export async function checkMicrophonePermission(): Promise<MicrophonePermissionResult> {
  if (!isMicrophoneSupported()) {
    return {
      status: "unsupported",
      message: "Microphone access is not supported in this browser.",
    };
  }

  if (!navigator.permissions) {
    return {
      status: "prompt",
      message: "Microphone permission status cannot be checked. Request access to continue.",
    };
  }

  try {
    const permission = await navigator.permissions.query({
      name: "microphone" as PermissionName,
    });

    return {
      status: permission.state,
      message:
        permission.state === "granted"
          ? "Microphone permission granted."
          : permission.state === "denied"
            ? "Microphone permission denied."
            : "Microphone permission has not been requested.",
    };
  } catch {
    return {
      status: "error",
      message: "Unable to check microphone permission.",
    };
  }
}

/**
 * Stop all microphone tracks and release the device.
 */
export function stopMicrophone(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}