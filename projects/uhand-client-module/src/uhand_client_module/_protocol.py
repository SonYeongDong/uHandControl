"""Version 2 UTF-8 newline-delimited JSON protocol; no device dependencies."""
import json

from ._validation import status_result
from .errors import (
    BusyError, DeviceError, InputValidationError, ProtocolError,
    RemoteError, UnsupportedFrequencyError,
)

VERSION = 2
MAX_FRAME_BYTES = 65536  # Includes the terminating LF.
MAX_REQUEST_ID = 2**53 - 1
REMOTE_ERRORS = {
    "BUSY": BusyError,
    "DEVICE_ERROR": DeviceError,
    "UNSUPPORTED_FREQUENCY": UnsupportedFrequencyError,
}


def request_frame(request_id, method, params):
    value = {"version": VERSION, "request_id": request_id, "method": method, "params": params}
    frame = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolError("Outgoing frame exceeds the byte limit.")
    return frame


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key.")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError(f"Non-JSON constant: {value}")


def response_frame(frame):
    if len(frame) + 1 > MAX_FRAME_BYTES:
        raise ProtocolError("Response frame exceeds the byte limit.")
    try:
        value = json.loads(frame.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ProtocolError("Invalid UTF-8 JSON response.") from exc
    if type(value) is not dict:
        raise ProtocolError("Response must be an object.")
    if type(value.get("version")) is not int or value["version"] != VERSION:
        raise ProtocolError("Unsupported protocol version.")
    rid = value.get("request_id")
    if type(rid) is not int or not 1 <= rid <= MAX_REQUEST_ID:
        raise ProtocolError("Invalid response request_id.")
    if type(value.get("ok")) is not bool:
        raise ProtocolError("Response ok must be bool.")
    expected = {"version", "request_id", "ok", "result" if value["ok"] else "error"}
    if set(value) != expected:
        raise ProtocolError("Unexpected response fields.")
    if not value["ok"]:
        error = value["error"]
        if (type(error) is not dict or set(error) != {"code", "message"}
                or type(error["code"]) is not str or not 1 <= len(error["code"]) <= 64
                or type(error["message"]) is not str or len(error["message"]) > 1024):
            raise ProtocolError("Invalid error object.")
    return value


def response_outcome(value, method):
    if not value["ok"]:
        error = value["error"]
        error_type = REMOTE_ERRORS.get(error["code"], RemoteError)
        return None, error_type(error["code"], error["message"])
    result = value["result"]
    if method == "GetStatus":
        try:
            status_result(result)
        except InputValidationError as exc:
            raise ProtocolError(str(exc)) from exc
    elif result is not None:
        raise ProtocolError(f"{method} must return null on success.")
    return result, None
