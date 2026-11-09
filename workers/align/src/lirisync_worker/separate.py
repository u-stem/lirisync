"""The `separate` method: extract the vocals of an audio file into a WAV file."""

import os
import secrets
import stat
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints, ValidationError

from lirisync_worker.audio_io import decode_audio, encode_wav
from lirisync_worker.protocol import ProtocolError, describe_validation_error
from lirisync_worker.separation.demix import Audio, chunk_count, demix
from lirisync_worker.separation.model import MaskModel
from lirisync_worker.separation.stft import SAMPLE_RATE

if TYPE_CHECKING:
    from lirisync_worker.server import Session

STAGE = "separate"
CHANNELS = 2
MS_PER_SECOND = 1000

type Process = Callable[[Audio], Audio]
type Decoder = Callable[[Path], Audio]
type Encoder = Callable[[Audio, Path], None]
type ModelLoader = Callable[[Path], Process]

type _FileState = tuple[int, int]  # st_mtime_ns, st_size
type _Path = Annotated[StrictStr, StringConstraints(min_length=1)]


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input: _Path
    output: _Path
    model: _Path


def load_mask_model(path: Path) -> Process:
    return MaskModel(path)


def make_separate(
    *,
    decoder: Decoder = decode_audio,
    encoder: Encoder = encode_wav,
    model_loader: ModelLoader = load_mask_model,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[["Session", Mapping[str, object]], dict[str, object]]:
    """The handler.

    Only the most recently used model is kept, so a worker that is handed many
    model files does not accumulate sessions. It is loaded again when another
    file is used or when the file's modification time or size changes.
    """
    latest: list[tuple[Path, _FileState, Process]] = []

    def model_for(path: Path, state: _FileState) -> Process:
        if latest and latest[0][:2] == (path, state):
            return latest[0][2]
        # Release the previous session before loading the next one, so two
        # models are never in memory at once.
        latest.clear()
        try:
            loaded = model_loader(path)
        except ImportError as exc:
            raise ProtocolError(
                "internal", f"cannot load the inference runtime: {_first_line(exc)}"
            ) from None
        except MemoryError:
            raise ProtocolError(
                "internal", f"out of memory while loading model file {path}"
            ) from None
        except Exception as exc:  # onnxruntime raises its own types for bad files
            raise ProtocolError(
                "model_missing", f"cannot use model file {path}: {_first_line(exc)}"
            ) from None
        latest[:] = [(path, state, loaded)]
        return loaded

    def separate(session: "Session", params: Mapping[str, object]) -> dict[str, object]:
        parsed = _parse(params)
        input_path = _resolve(parsed.input, "input")
        output_path = _resolve(parsed.output, "output")
        model_path = _resolve(parsed.model, "model")
        _check_input(input_path)
        _check_output(input_path, output_path)
        model_state = _model_state(model_path)

        audio = decoder(input_path)
        samples = audio.shape[-1]
        if samples == 0:
            raise ProtocolError("audio_unreadable", f"{input_path.name} has no audio samples")
        model = model_for(model_path, model_state)

        total = chunk_count(samples)
        started = clock()
        done = 0

        def process(chunk: Audio) -> Audio:
            nonlocal done
            vocals = model(chunk)
            done += 1
            elapsed = clock() - started
            eta_ms = int(elapsed / done * (total - done) * MS_PER_SECOND)
            session.progress(STAGE, done / total, eta_ms)
            return vocals

        session.progress(STAGE, 0.0, None)
        vocals = demix(audio, process)
        _write_atomically(encoder, vocals, output_path)
        return {
            "durationMs": samples * MS_PER_SECOND // SAMPLE_RATE,
            "sampleRate": SAMPLE_RATE,
            "channels": CHANNELS,
        }

    return separate


def _parse(params: Mapping[str, object]) -> _Params:
    try:
        return _Params.model_validate(params)
    except ValidationError as exc:
        problems = describe_validation_error(exc)
        raise ProtocolError(
            "invalid_request", f"separate params do not match the schema ({problems})"
        ) from None


def _resolve(text: str, what: str) -> Path:
    """Absolute form of a path from the host; text the OS cannot use is a bad request."""
    try:
        return Path(text).resolve()
    except (ValueError, OSError, RuntimeError):  # UnicodeError is a ValueError
        raise ProtocolError("invalid_request", f"{what} is not a usable path") from None


def _check_input(input_path: Path) -> None:
    """Refuse what is not a plain file before ffmpeg opens it: a FIFO would block it forever.

    A path that does not exist is left to ffmpeg, which reports it as unreadable.
    """
    try:
        exists = input_path.exists()
        regular = input_path.is_file()
    except (ValueError, OSError):
        raise ProtocolError("invalid_request", "input is not a usable path") from None
    if exists and not regular:
        raise ProtocolError("invalid_request", f"input is not a regular file: {input_path}")


def _check_output(input_path: Path, output_path: Path) -> None:
    if output_path.suffix.lower() != ".wav":
        raise ProtocolError("invalid_request", "output must be a .wav file")
    if not output_path.parent.is_dir():
        raise ProtocolError(
            "invalid_request", f"output directory does not exist: {output_path.parent}"
        )
    if output_path.is_dir():
        raise ProtocolError("invalid_request", f"output is a directory: {output_path}")
    if _same_file(input_path, output_path):
        raise ProtocolError("invalid_request", "output must not be the input file")


def _same_file(first: Path, second: Path) -> bool:
    """True for one path spelled two ways, a hard link, or a case variant on a case-folding disk."""
    if first == second:
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:  # one of them does not exist
        return False


def _model_state(path: Path) -> _FileState:
    try:
        status = path.stat()
    except (OSError, ValueError):
        raise ProtocolError("model_missing", f"model file not found: {path}") from None
    if not stat.S_ISREG(status.st_mode):
        raise ProtocolError("model_missing", f"model path is not a file: {path}")
    return (status.st_mtime_ns, status.st_size)


def _write_atomically(encoder: Encoder, audio: Audio, output: Path) -> None:
    """Encode beside `output` under a short temporary name, then rename over it."""
    temporary = output.with_name(f".lirisync-{secrets.token_hex(8)}.tmp.wav")
    try:
        encoder(audio, temporary)
        os.replace(temporary, output)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ProtocolError(
            "internal", f"cannot write {output.name}: {exc.strerror or exc}"
        ) from None
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__
