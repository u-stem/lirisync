"""Checks and caching shared by the methods that read files the host names.

Paths come from the host as text. They are resolved and checked here before an
external program (ffmpeg) or the inference runtime opens them, so a bad path is
reported as a protocol error instead of a hang or a traceback.
"""

import stat
from collections.abc import Callable, Hashable
from pathlib import Path

from lirisync_worker.protocol import ProtocolError

type FileState = tuple[int, int]  # st_mtime_ns, st_size


def resolve_path(text: str, what: str) -> Path:
    """Absolute form of a path from the host; text the OS cannot use is a bad request."""
    try:
        return Path(text).resolve()
    except (ValueError, OSError, RuntimeError):  # UnicodeError is a ValueError
        raise ProtocolError("invalid_request", f"{what} is not a usable path") from None


def check_input_file(path: Path, what: str) -> None:
    """Refuse what is not a plain file before ffmpeg opens it: a FIFO would block it forever.

    A path that does not exist is left to ffmpeg, which reports it as unreadable.
    """
    try:
        exists = path.exists()
        regular = path.is_file()
    except (ValueError, OSError):
        raise ProtocolError("invalid_request", f"{what} is not a usable path") from None
    if exists and not regular:
        raise ProtocolError("invalid_request", f"{what} is not a regular file: {path}")


def model_file_state(path: Path) -> FileState:
    """Modification time and size of a model file, or `model_missing`."""
    try:
        status = path.stat()
    except (OSError, ValueError):
        raise ProtocolError("model_missing", f"model file not found: {path}") from None
    if not stat.S_ISREG(status.st_mode):
        raise ProtocolError("model_missing", f"model path is not a file: {path}")
    return (status.st_mtime_ns, status.st_size)


def first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


class LatestModel[M]:
    """Keeps only the most recently used model, so a worker handed many does not pile them up.

    A model is loaded again when another path is used or when its state changes:
    the `model_file_state` of each file the model is read from. `describe` names
    the path in error messages.
    """

    def __init__(self, loader: Callable[[Path], M], describe: Callable[[Path], str]) -> None:
        self._loader = loader
        self._describe = describe
        self._latest: list[tuple[Path, Hashable, M]] = []

    def get(self, path: Path, state: Hashable) -> M:
        if self._latest and self._latest[0][:2] == (path, state):
            return self._latest[0][2]
        # Release the previous model before loading the next one, so two are
        # never in memory at once.
        self._latest.clear()
        try:
            loaded = self._loader(path)
        except ImportError as exc:
            raise ProtocolError(
                "internal", f"cannot load the inference runtime: {first_line(exc)}"
            ) from None
        except MemoryError:
            raise ProtocolError(
                "internal", f"out of memory while loading {self._describe(path)}"
            ) from None
        except Exception as exc:  # onnxruntime raises its own types for bad files
            raise ProtocolError(
                "model_missing", f"cannot use {self._describe(path)}: {first_line(exc)}"
            ) from None
        self._latest[:] = [(path, state, loaded)]
        return loaded
