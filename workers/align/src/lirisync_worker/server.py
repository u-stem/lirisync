"""Method registry, dispatch, and the request loop."""

import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass

from lirisync_worker import __version__
from lirisync_worker.protocol import (
    PROTOCOL_VERSION,
    Message,
    ProtocolChannel,
    ProtocolError,
    error_message,
    parse_request,
    result_message,
)


@dataclass
class Session:
    """State shared with handlers while the loop runs."""

    methods: list[str]
    exit_requested: bool = False


Handler = Callable[[Session, Mapping[str, object]], dict[str, object]]


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


def _require_no_params(params: Mapping[str, object]) -> None:
    if params:
        raise ProtocolError("invalid_request", "this method takes no params")


def hello(session: Session, params: Mapping[str, object]) -> dict[str, object]:
    _require_no_params(params)
    return {
        "protocol": PROTOCOL_VERSION,
        "worker": __version__,
        "methods": list(session.methods),
    }


def shutdown(session: Session, params: Mapping[str, object]) -> dict[str, object]:
    _require_no_params(params)
    session.exit_requested = True
    return {}


def default_registry() -> Registry:
    return Registry({"hello": hello, "shutdown": shutdown})


class Server:
    def __init__(self, registry: Registry | None = None) -> None:
        self._registry = registry if registry is not None else default_registry()
        self._session = Session(methods=self._registry.methods())

    def handle_line(self, line: str) -> Message:
        """Turn one input line into exactly one response message."""
        request_id: str | None = None
        try:
            request = parse_request(line)
            request_id = request.id
            handler = self._registry.get(request.method)
            if handler is None:
                raise ProtocolError("unknown_method", f"unknown method: {request.method}")
            return result_message(request.id, handler(self._session, request.params))
        except ProtocolError as exc:
            return error_message(exc.request_id or request_id, exc.code, exc.message)
        except Exception as exc:  # the loop must never die on a handler bug
            print(f"internal error: {exc!r}", file=sys.stderr, flush=True)  # noqa: T201
            return error_message(request_id, "internal", "internal error; see worker log")

    def serve(self, lines: Iterable[str], channel: ProtocolChannel) -> int:
        """Process lines until shutdown or end of input. Returns the exit code."""
        for line in _non_blank(lines):
            channel.send(self.handle_line(line))
            if self._session.exit_requested:
                break
        return 0


def _non_blank(lines: Iterable[str]) -> Iterator[str]:
    return (line for line in lines if line.strip())
