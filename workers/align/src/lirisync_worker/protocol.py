"""Wire format: request parsing, message encoding, and the private protocol channel."""

import ctypes
import json
import os
import sys
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, StringConstraints, ValidationError

PREFIX = "@@lirisync "
PROTOCOL_VERSION = 1

ErrorCode = Literal[
    "invalid_request",
    "unknown_method",
    "unsupported_version",
    "internal",
    "gpu_unavailable",
    "model_missing",
    "asr_degenerate",
    "cancelled",
]

Message = dict[str, object]


class ProtocolError(Exception):
    """A failure that is reported to the host as an ``error`` message."""

    def __init__(self, code: ErrorCode, message: str, request_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


class Request(BaseModel):
    """A request as it arrives on stdin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    v: StrictInt
    id: Annotated[StrictStr, StringConstraints(min_length=1)]
    method: Annotated[StrictStr, StringConstraints(min_length=1)]
    params: dict[str, Any]


def _reject_constant(name: str) -> object:
    raise ValueError(f"non-standard JSON constant: {name}")


def _usable_id(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_request(line: str) -> Request:
    """Parse one stdin line into a ``Request``.

    Raises ``ProtocolError`` (``invalid_request`` or ``unsupported_version``)
    carrying the request id whenever it could be recovered.
    """
    try:
        raw = json.loads(line, parse_constant=_reject_constant)
    except ValueError:
        raise ProtocolError("invalid_request", "request is not valid JSON") from None
    if not isinstance(raw, dict):
        raise ProtocolError("invalid_request", "request must be a JSON object")

    request_id = _usable_id(raw.get("id"))
    version = raw.get("v")
    # A different protocol version may legitimately use a different shape, so
    # report the version mismatch before judging the rest of the request.
    if isinstance(version, int) and not isinstance(version, bool) and version != PROTOCOL_VERSION:
        raise ProtocolError(
            "unsupported_version",
            f"protocol version {version} is not supported; this worker speaks {PROTOCOL_VERSION}",
            request_id,
        )
    try:
        return Request.model_validate(raw)
    except ValidationError as exc:
        # Report only locations and reasons; never echo input values.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors(include_input=False, include_url=False)
        )
        raise ProtocolError(
            "invalid_request", f"request does not match the schema ({problems})", request_id
        ) from None


def result_message(request_id: str, result: Mapping[str, object]) -> Message:
    return {"id": request_id, "type": "result", "result": dict(result)}


def error_message(request_id: str | None, code: ErrorCode, message: str) -> Message:
    return {"id": request_id, "type": "error", "code": code, "message": message}


def encode_message(message: Mapping[str, object]) -> str:
    """Encode a message as one prefixed, compact, newline-terminated line."""
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return f"{PREFIX}{body}\n"


class ProtocolChannel:
    """Writes protocol messages, one flushed line each, to a dedicated stream."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def send(self, message: Mapping[str, object]) -> None:
        self._stream.write(encode_message(message))
        self._stream.flush()


_STD_OUTPUT_HANDLE = -11


def _point_win32_stdout_handle_at_stderr() -> None:
    """Make the Windows standard-output handle match the redirected fd 1.

    ``os.dup2`` only rewires the C runtime's fd table. Child processes (and
    native code) that read ``GetStdHandle(STD_OUTPUT_HANDLE)`` would otherwise
    still be handed the original pipe, which carries the protocol.
    """
    if sys.platform != "win32":
        return
    import msvcrt  # noqa: PLC0415 - exists only on Windows
    from ctypes import wintypes  # noqa: PLC0415 - loads cleanly only on Windows

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel32.SetStdHandle.restype = wintypes.BOOL
    if not kernel32.SetStdHandle(_STD_OUTPUT_HANDLE, msvcrt.get_osfhandle(2)):
        raise ctypes.WinError(ctypes.get_last_error())


def redirect_stdout() -> ProtocolChannel:
    """Reserve the original stdout for the protocol and point stdout at stderr.

    After this call, ``print``, C-level writes to fd 1, and the stdout of child
    processes started without an explicit ``stdout`` all land on stderr.
    Must run before importing anything that might write to stdout.
    """
    sys.stdout.flush()
    # os.dup returns a non-inheritable fd, so children never receive the
    # protocol pipe through it. On POSIX they inherit fd 1 (now stderr); on
    # Windows they inherit the std handle, which is repointed below.
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    _point_win32_stdout_handle_at_stderr()
    sys.stdout = sys.stderr
    stream = open(  # noqa: SIM115 - lives for the whole process
        protocol_fd, "w", encoding="utf-8", errors="backslashreplace", newline="\n"
    )
    return ProtocolChannel(stream)
