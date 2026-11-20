"""Public exceptions. Transport failure does not prove a command was not executed."""


class UHandError(Exception):
    """Base exception for the client."""


class InputValidationError(UHandError, ValueError):
    """Invalid local argument; nothing was sent."""


class NotConnectedError(UHandError):
    """No established connection."""


class AlreadyConnectedError(UHandError):
    """Disconnect before connecting again."""


class ConnectionFailedError(UHandError):
    """TCP connection could not be established."""


class DisconnectedError(UHandError):
    """Connection closed; an in-flight operation may still run on the server."""


class RequestTimeoutError(UHandError, TimeoutError):
    """Response deadline expired; execution outcome may be unknown."""


class ProtocolError(UHandError):
    """Peer violated the protocol; the connection has been closed."""


class RemoteError(UHandError):
    """A valid server error response."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class BusyError(RemoteError):
    """Server is owned by another client or an output is already running."""


class DeviceError(RemoteError):
    """The server reported an output-device failure."""


class UnsupportedFrequencyError(RemoteError):
    """The device backend does not support the requested frequency."""
