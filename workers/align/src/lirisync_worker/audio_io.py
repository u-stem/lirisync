"""Audio file decoding and WAV encoding through an external ffmpeg process.

ffmpeg is a separate program, not a Python dependency: the executable is named
by ``LIRISYNC_FFMPEG`` when set, otherwise ``ffmpeg`` is looked up on ``PATH``.
Audio crosses the process boundary as raw interleaved little-endian float32,
so nothing is quantized on the way in or out.
"""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from lirisync_worker.protocol import ProtocolError
from lirisync_worker.separation.demix import STEREO, Audio
from lirisync_worker.separation.stft import SAMPLE_RATE

FFMPEG_ENV = "LIRISYNC_FFMPEG"
_STDERR_TAIL_CHARS = 500
_BYTES_PER_FRAME = 4 * STEREO
# Keeps a console window from flashing for each child on Windows; 0 elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_executable() -> str:
    """The ffmpeg to run: ``LIRISYNC_FFMPEG`` if set and not empty, else ``ffmpeg``."""
    return os.environ.get(FFMPEG_ENV) or "ffmpeg"


def stderr_tail(stderr: bytes) -> str:
    """The end of ffmpeg's error output, where the cause is, trimmed."""
    text = stderr.decode("utf-8", errors="replace").strip()
    return text[-_STDERR_TAIL_CHARS:]


# Shell conventions for "found but not executable" and "not found", and any
# negative code (killed by a signal): the process never got to judge the file.
_CANNOT_RUN = (126, 127)


def _killed_or_unrunnable(returncode: int) -> bool:
    return returncode < 0 or returncode in _CANNOT_RUN


def _run_ffmpeg(arguments: list[str], stdin: bytes | None) -> subprocess.CompletedProcess[bytes]:
    executable = ffmpeg_executable()
    try:
        return subprocess.run(
            [executable, *arguments],
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
            capture_output=True,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        raise ProtocolError(
            "ffmpeg_missing",
            f"cannot run ffmpeg ({executable}): {exc.strerror or exc}. "
            f"Install it or set {FFMPEG_ENV} to its path",
        ) from None


def decode_audio(path: Path) -> Audio:
    """Decode the first audio stream of `path` to 44.1 kHz stereo float32, `[2, n]`.

    Raises ``ProtocolError`` ``ffmpeg_missing`` if ffmpeg cannot be started and
    ``audio_unreadable`` if it rejects the file, and ``internal`` if it was killed
    or could not run. Output on stderr after a clean exit is logged to stderr.
    An empty result is returned as is.
    """
    completed = _run_ffmpeg(
        [
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ac",
            str(STEREO),
            "-ar",
            str(SAMPLE_RATE),
            "-",
        ],
        None,
    )
    if completed.returncode != 0:
        detail = f"(exit {completed.returncode}): {stderr_tail(completed.stderr)}"
        if _killed_or_unrunnable(completed.returncode):
            raise ProtocolError("internal", f"ffmpeg was killed or could not run {detail}")
        raise ProtocolError("audio_unreadable", f"ffmpeg could not decode {path.name} {detail}")
    if completed.stderr.strip():
        # Kept out of the protocol: the host reads stdout only, stderr is the log.
        sys.stderr.write(
            f"ffmpeg warned while decoding {path.name}: {stderr_tail(completed.stderr)}\n"
        )
        sys.stderr.flush()
    usable = len(completed.stdout) - len(completed.stdout) % _BYTES_PER_FRAME
    samples = np.frombuffer(completed.stdout[:usable], dtype="<f4")
    return np.ascontiguousarray(samples.reshape(-1, STEREO).T, dtype=np.float32)


def encode_wav(audio: Audio, path: Path) -> None:
    """Write `[2, n]` float32 audio as a 32-bit float WAV at `path`, replacing any file there.

    Raises ``ProtocolError`` ``ffmpeg_missing`` if ffmpeg cannot be started and
    ``internal`` if it fails.
    """
    interleaved = np.ascontiguousarray(audio.T, dtype="<f4").tobytes()
    completed = _run_ffmpeg(
        [
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "f32le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(STEREO),
            "-i",
            "-",
            "-c:a",
            "pcm_f32le",
            str(path),
        ],
        interleaved,
    )
    if completed.returncode != 0:
        detail = f"(exit {completed.returncode}): {stderr_tail(completed.stderr)}"
        if _killed_or_unrunnable(completed.returncode):
            raise ProtocolError("internal", f"ffmpeg was killed or could not run {detail}")
        raise ProtocolError("internal", f"ffmpeg could not write {path.name} {detail}")
