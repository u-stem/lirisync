"""Method registry, dispatch, and the request loop."""

import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass

from lirisync_worker import __version__
from lirisync_worker.anchor import make_anchor
from lirisync_worker.match_text import Reader
from lirisync_worker.protocol import (
    PROTOCOL_VERSION,
    Message,
    ProtocolChannel,
    ProtocolError,
    encode_message,
    error_message,
    parse_request,
    progress_message,
    result_message,
)
from lirisync_worker.separate import make_separate

type ProgressSink = Callable[[str, float, int | None], None]
type Handler = Callable[[Session, Mapping[str, object]], dict[str, object]]


class Registry:
    """Maps method names to handlers, keeping registration order."""

    def __init__(self, handlers: Mapping[str, Handler] | None = None) -> None:
        self._handlers: dict[str, Handler] = dict(handlers or {})

    def register(self, name: str, handler: Handler) -> None:
        self._handlers[name] = handler

    def get(self, name: str) -> Handler | None:
        return self._handlers.get(name)

    def methods(self) -> list[str]:
        return list(self._handlers)


@dataclass
class Session:
    """State shared with handlers while the loop runs."""

    registry: Registry
    exit_requested: bool = False
    # Bound by the server to the request being handled; None between requests.
    progress_sink: ProgressSink | None = None

    def progress(self, stage: str, ratio: float, eta_ms: int | None) -> None:
        """Report progress of the request being handled; a no-op outside one."""
        if self.progress_sink is not None:
            self.progress_sink(stage, ratio, eta_ms)


def _require_no_params(params: Mapping[str, object]) -> None:
    if params:
        raise ProtocolError("invalid_request", "this method takes no params")


def hello(session: Session, params: Mapping[str, object]) -> dict[str, object]:
    _require_no_params(params)
    return {
        "protocol": PROTOCOL_VERSION,
        "worker": __version__,
        "methods": session.registry.methods(),
    }


def shutdown(session: Session, params: Mapping[str, object]) -> dict[str, object]:
    _require_no_params(params)
    session.exit_requested = True
    return {}


def _sudachi_reader() -> Reader:
    # Imported on first use: loading SudachiPy and its dictionary is the slow part.
    from lirisync_worker.sudachi_reader import SudachiReader  # noqa: PLC0415

    return SudachiReader()


def default_registry() -> Registry:
    return Registry(
        {
            "hello": hello,
            "anchor": make_anchor(_sudachi_reader),
            "separate": make_separate(),
            "shutdown": shutdown,
        }
    )


class Server:
    def __init__(self, registry: Registry | None = None) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._session = Session(registry=self._registry)

    def handle_line(self, line: str, emit: Callable[[Message], None] | None = None) -> Message:
        """Turn one input line into exactly one final message.

        Progress a handler reports is passed to `emit` as it happens, before
        this returns; without `emit` it is dropped.
        """
        request_id: str | None = None
        try:
            request = parse_request(line)
            request_id = request.id
            handler = self._registry.get(request.method)
            if handler is None:
                raise ProtocolError("unknown_method", f"unknown method: {request.method}")
            self._session.progress_sink = _progress_sink(request.id, emit)
            try:
                result = handler(self._session, request.params)
            finally:
                self._session.progress_sink = None
            message = result_message(request.id, result)
            # Serialization failures (NaN, non-JSON types) are handler bugs too,
            # so surface them here rather than when the channel writes the line.
            encode_message(message)
            return message
        except ProtocolError as exc:
            return error_message(exc.request_id or request_id, exc.code, exc.message)
        except Exception as exc:  # the loop must never die on a handler bug
            print(f"internal error: {exc!r}", file=sys.stderr, flush=True)  # noqa: T201
            return error_message(request_id, "internal", "internal error; see worker log")

    def serve(self, lines: Iterable[str], channel: ProtocolChannel) -> int:
        """Process lines until shutdown or end of input. Returns the exit code."""
        for line in _non_blank(lines):
            channel.send(self.handle_line(line, channel.send))
            if self._session.exit_requested:
                break
        return 0


def _progress_sink(request_id: str, emit: Callable[[Message], None] | None) -> ProgressSink:
    def sink(stage: str, ratio: float, eta_ms: int | None) -> None:
        if emit is None:
            return
        message = progress_message(request_id, stage, ratio, eta_ms)
        # Fails here, inside the handler, for NaN and non-JSON values, so the
        # request ends in an `internal` error instead of a half-written line.
        encode_message(message)
        emit(message)

    return sink


def _non_blank(lines: Iterable[str]) -> Iterator[str]:
    return (line for line in lines if line.strip())
