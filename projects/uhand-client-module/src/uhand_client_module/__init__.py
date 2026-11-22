"""uHandClientModule: six blocking functions, concurrent GetStatus supported.

The module owns one connection per Python process. Importing it performs no I/O.
"""
from ._transport import _Client
from ._validation import buzzer_params, led_params, pulse_params
from .errors import (
    UHandError, InputValidationError, NotConnectedError, AlreadyConnectedError,
    ConnectionFailedError, DisconnectedError, RequestTimeoutError, ProtocolError,
    RemoteError, BusyError, DeviceError, UnsupportedFrequencyError,
)

__version__ = "1.0.1"
__all__ = [
    "Connect", "Disconnect", "SetuHandPulse", "SetuHandBuzzer", "SetuHandLED", "GetStatus",
    "UHandError", "InputValidationError", "NotConnectedError", "AlreadyConnectedError",
    "ConnectionFailedError", "DisconnectedError", "RequestTimeoutError", "ProtocolError",
    "RemoteError", "BusyError", "DeviceError", "UnsupportedFrequencyError",
]
_client = _Client()


def Connect(IP: str, Port: int) -> None:
    """Establish a TCP connection and obtain server ownership (5-second deadline)."""
    _client.connect(IP, Port)


def Disconnect() -> None:
    """Close the connection. Does not stop robot movement; safe when disconnected."""
    _client.disconnect()


def SetuHandPulse(
    Finger1Pulse: int, Finger2Pulse: int, Finger3Pulse: int,
    Finger4Pulse: int, Finger5Pulse: int, WristPulse: int,
    RunningTime: int,
) -> None:
    """Send pulses: thumb 800..2200, fingers 2..5 800..2000, wrist 500..2500."""
    params = pulse_params(
        (Finger1Pulse, Finger2Pulse, Finger3Pulse, Finger4Pulse, Finger5Pulse, WristPulse),
        RunningTime,
    )
    _client.request("SetuHandPulse", params)


def SetuHandBuzzer(Frequency: int, RunningTime: int, Continuous: bool = False) -> None:
    """Apply a tone or 0Hz silence. Continuous mode returns without a time wait."""
    _client.request("SetuHandBuzzer", buzzer_params(Frequency, RunningTime, Continuous))


def SetuHandLED(Red=None, Green=None, Blue=None, Brightness=100, **legacy) -> None:
    """RGB 0..255, brightness 0..100. Legacy True/False maps to 255/0."""
    channels = [Red, Green, Blue]
    for index, key in enumerate(("RedEnable", "GreenEnable", "BlueEnable")):
        if key in legacy:
            if channels[index] is not None:
                raise InputValidationError(f"Duplicate channel: {key}")
            channels[index] = legacy.pop(key)
    if legacy:
        raise InputValidationError("Unexpected LED parameter.")
    params = led_params(*channels, Brightness)
    if all(type(channel) is bool for channel in channels) and Brightness == 100:
        # Keep original boolean calls usable with previously deployed v2 servers.
        params = dict(zip(("RedEnable", "GreenEnable", "BlueEnable"), channels))
    _client.request("SetuHandLED", params)


def GetStatus() -> dict:
    """Return the last completed state, including source RGB and LEDBrightness."""
    try:
        result = _client.request("GetStatus", {"IncludeLEDBrightness": True})
    except RemoteError as exc:
        if (exc.code, exc.message) != ("INVALID_ARGUMENT", "Unexpected parameters for GetStatus."):
            raise
        result = _client.request("GetStatus", {})
    if "LEDBrightness" not in result:
        rgb = result["LED"]
        result["LEDBrightness"] = None if rgb is None else 100
        if rgb is not None:
            result["LED"] = [255 * channel for channel in rgb]
    return result
