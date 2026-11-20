"""Server-side protocol v2 decoding; no GUI imports."""
import json
import ipaddress

MAX_FRAME = 65536
MAX_ID = 2**53 - 1
PULSE_NAMES = tuple(f"Finger{i}Pulse" for i in range(1, 6)) + ("WristPulse",)
PULSE_LIMITS = ((800, 2200), (800, 2000), (800, 2000), (800, 2000), (800, 2000), (500, 2500))
EMPTY_STATUS = {
    "TargetPulses": None, "PulseRunningTime": None,
    "BuzzerFrequency": None, "BuzzerRunningTime": None, "BuzzerContinuous": None, "LED": None, "LEDBrightness": None,
}


class CommandError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise CommandError("INVALID_ARGUMENT", f"{name}: expected integer {low}..{high}, excluding bool.")


def validate_bind(host, port):
    if type(host) is not str or "%" in host:
        raise ValueError("Use an IPv4 or IPv6 address without a scope ID.")
    address = ipaddress.ip_address(host)
    integer("Port", port, 0, 65535)  # 0 is internal/test auto-allocation, never a Client port.
    return address


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key.")
        value[key] = item
    return value


def _constant(value):
    raise ValueError("Non-finite JSON constant.")


def decode(frame):
    if len(frame) + 1 > MAX_FRAME:
        raise ValueError("Frame limit exceeded.")
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid UTF-8 JSON.") from exc
    if type(value) is not dict:
        raise ValueError("Request must be an object.")
    rid = value.get("request_id")
    if type(rid) is not int or not 1 <= rid <= MAX_ID:
        raise ValueError("Invalid request ID.")
    return value


def validate_request(value):
    if set(value) != {"version", "request_id", "method", "params"}:
        raise CommandError("INVALID_ARGUMENT", "Unexpected request fields.")
    if type(value["version"]) is not int or value["version"] != 2:
        raise CommandError("UNSUPPORTED_VERSION", "Expected protocol version 2.")
    method, params = value["method"], value["params"]
    if type(method) is not str or type(params) is not dict:
        raise CommandError("INVALID_ARGUMENT", "method must be string and params must be object.")
    if method == "GetStatus" and "IncludeLEDBrightness" in params:
        expected = {"IncludeLEDBrightness"}
        if type(params["IncludeLEDBrightness"]) is not bool:
            raise CommandError("INVALID_ARGUMENT", "IncludeLEDBrightness must be bool.")
    elif method in ("Hello", "GetStatus"):
        expected = set()
    elif method == "SetuHandPulse":
        expected = set(PULSE_NAMES) | {"RunningTime"}
    elif method == "SetuHandBuzzer":
        params = dict(params)
        params.setdefault("Continuous", False)
        expected = {"Frequency", "RunningTime", "Continuous"}
    elif method == "SetuHandLED":
        legacy = {"RedEnable", "GreenEnable", "BlueEnable"}
        if set(params) == legacy:
            if any(type(v) is not bool for v in params.values()):
                raise CommandError("INVALID_ARGUMENT", "Legacy LED channels must be bool.")
            params = {key: 255 * params[key + "Enable"] for key in ("Red", "Green", "Blue")}
        params = {"Brightness": 100, **params}
        expected = {"Red", "Green", "Blue", "Brightness"}
    else:
        raise CommandError("UNKNOWN_METHOD", "Unknown method.")
    if set(params) != expected:
        raise CommandError("INVALID_ARGUMENT", f"Unexpected parameters for {method}.")
    if method == "SetuHandPulse":
        for name, (low, high) in zip(PULSE_NAMES, PULSE_LIMITS):
            integer(name, params[name], low, high)
    if method in ("SetuHandPulse", "SetuHandBuzzer"):
        integer("RunningTime", params["RunningTime"], 100, 20000)
    if method == "SetuHandBuzzer":
        integer("Frequency", params["Frequency"], 0, 10000)
        if type(params["Continuous"]) is not bool:
            raise CommandError("INVALID_ARGUMENT", "Continuous must be bool.")
    if method == "SetuHandLED":
        for channel in ("Red", "Green", "Blue"):
            integer(channel, params[channel], 0, 255)
        integer("Brightness", params["Brightness"], 0, 100)
    return method, params


def response(rid, result=None, error=None):
    value = {"version": 2, "request_id": rid, "ok": error is None}
    value["result" if error is None else "error"] = (
        result if error is None else {"code": error.code, "message": str(error.message)[:1024]}
    )
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
