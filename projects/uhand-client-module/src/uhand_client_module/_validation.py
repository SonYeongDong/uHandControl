"""Argument checks shared by the public calls and response validation."""
import ipaddress

from .errors import InputValidationError

PULSE_NAMES = (
    "Finger1Pulse", "Finger2Pulse", "Finger3Pulse",
    "Finger4Pulse", "Finger5Pulse", "WristPulse",
)
PULSE_LIMITS = ((800, 2200), (800, 2000), (800, 2000), (800, 2000), (800, 2000), (500, 2500))
STATUS_KEYS = (
    "TargetPulses", "PulseRunningTime", "BuzzerFrequency",
    "BuzzerRunningTime", "BuzzerContinuous", "LED",
)


def integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise InputValidationError(f"{name} must be an integer in {low}..{high} (bool excluded).")


def endpoint(ip, port):
    if type(ip) is not str:
        raise InputValidationError("IP must be an IPv4 or IPv6 address string.")
    # Hostnames, scope IDs and surrounding whitespace are intentionally excluded.
    if "%" in ip:
        raise InputValidationError("Scoped IPv6 addresses are not supported.")
    try:
        address = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise InputValidationError("IP must be an IPv4 or IPv6 address, not a hostname.") from exc
    integer("Port", port, 1, 65535)
    return address


def pulse_params(values, running_time):
    if len(values) != 6:
        raise InputValidationError("Six pulse values required.")
    for name, value, (low, high) in zip(PULSE_NAMES, values, PULSE_LIMITS):
        integer(name, value, low, high)
    integer("RunningTime", running_time, 100, 20000)
    return dict(zip(PULSE_NAMES, values), RunningTime=running_time)


def buzzer_params(frequency, running_time, continuous=False):
    integer("Frequency", frequency, 0, 10000)
    integer("RunningTime", running_time, 100, 20000)
    if type(continuous) is not bool:
        raise InputValidationError("Continuous must be bool.")
    return {"Frequency": frequency, "RunningTime": running_time, "Continuous": continuous}


def led_params(red, green, blue, brightness=100):
    integer("Brightness", brightness, 0, 100)
    values = {}
    for name, value in zip(("Red", "Green", "Blue"), (red, green, blue)):
        value = 255 * value if type(value) is bool else value
        integer(name, value, 0, 255)
        values[name] = value
    return dict(values, Brightness=brightness)


def status_result(value):
    if type(value) is not dict or set(value) not in (set(STATUS_KEYS), set(STATUS_KEYS) | {"LEDBrightness"}):
        raise InputValidationError("GetStatus must contain the expected status fields.")
    pulses, duration = value["TargetPulses"], value["PulseRunningTime"]
    if (pulses is None) != (duration is None):
        raise InputValidationError("Pulse values and time must both be null or both be present.")
    if pulses is not None:
        if type(pulses) is not list or len(pulses) != 6:
            raise InputValidationError("TargetPulses must be a six-item list.")
        pulse_params(pulses, duration)
    frequency, duration = value["BuzzerFrequency"], value["BuzzerRunningTime"]
    if (frequency is None) != (duration is None):
        raise InputValidationError("Buzzer frequency and time must both be null or both be present.")
    continuous = value["BuzzerContinuous"]
    if (frequency is None) != (continuous is None):
        raise InputValidationError("Buzzer fields must all be null or all be present.")
    if frequency is not None:
        buzzer_params(frequency, duration, continuous)
    led = value["LED"]
    extended = "LEDBrightness" in value
    if extended and (led is None) != (value["LEDBrightness"] is None):
        raise InputValidationError("LED and brightness must both be null or both present.")
    if led is not None:
        if type(led) is not list or len(led) != 3:
            raise InputValidationError("LED must be a three-item bool list.")
        if extended:
            for channel in led:
                integer("RGB", channel, 0, 255)
            integer("Brightness", value["LEDBrightness"], 0, 100)
        elif any(type(v) is not bool for v in led):
            raise InputValidationError("Legacy LED status requires boolean channels.")
    return value
