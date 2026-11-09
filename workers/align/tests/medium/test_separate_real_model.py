"""End to end: the worker process separates a real file with the real model.

Skipped unless `LIRISYNC_SEPARATOR_DIR` names a directory fetched with
`tools/fetch_separator_model.py` (see `test_separator_reference.py`), and
skipped without ffmpeg. The reference input is written to a WAV file, sent
through `separate` in a worker process, and the vocals read back are compared
with the reference stems the model ships with.
"""

import os
import shutil
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.audio_io import decode_audio, encode_wav, ffmpeg_executable
from tests.medium.support import WorkerRun, is_valid, request, run_worker

ENV_VAR = "LIRISYNC_SEPARATOR_DIR"
MODEL = "sep-all-int8.onnx"
REFERENCE_INPUT = "ref-input.f32"
REFERENCE_STEMS = "ref-stems-all-int8.f32"

# The reference stems are the model's output for the 8 s input as one chunk.
# The worker cuts that input into two half-overlapping chunks: the first half
# is the first chunk's output unchanged, but the second half comes from a chunk
# that starts at the half and is zero-padded, blended with a fade, so it
# differs from the reference. 43.1 dB was measured here on Apple silicon. 30 dB
# is a floor: far above what a layout, mask or channel-order bug gives (close to
# 0 dB), with room for the blend and for CPUs where the int8 model is less exact.
MIN_SNR_DB = 30.0
# Loading the model and running two chunks on a CPU can take a while.
SLOW_RUN_SECONDS = 300

Audio = npt.NDArray[np.float32]


@pytest.fixture(scope="module")
def separator_dir() -> Path:
    value = os.environ.get(ENV_VAR)
    if not value:
        pytest.skip(f"{ENV_VAR} is not set; see tools/fetch_separator_model.py")
    if shutil.which(ffmpeg_executable()) is None:
        pytest.skip("ffmpeg is not installed")
    directory = Path(value).expanduser()
    missing = [
        n for n in (MODEL, REFERENCE_INPUT, REFERENCE_STEMS) if not (directory / n).is_file()
    ]
    if missing:
        pytest.skip(f"{ENV_VAR}={directory} lacks {missing}; see tools/fetch_separator_model.py")
    return directory


def _read_interleaved(path: Path) -> Audio:
    samples = np.fromfile(path, dtype="<f4")
    return np.ascontiguousarray(samples.reshape(-1, 2).T, dtype=np.float32)


def _snr_db(reference: Audio, estimate: Audio) -> float:
    signal = float(np.sum(reference.astype(np.float64) ** 2))
    noise = float(np.sum((reference.astype(np.float64) - estimate.astype(np.float64)) ** 2))
    return float("inf") if noise == 0.0 else 10.0 * float(np.log10(signal / noise))


@pytest.fixture(scope="module")
def vocals_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("separate-real") / "vocals.wav"


@pytest.fixture(scope="module")
def session(separator_dir: Path, vocals_path: Path) -> WorkerRun:
    song = vocals_path.parent / "song.wav"
    encode_wav(_read_interleaved(separator_dir / REFERENCE_INPUT), song)
    params = {
        "input": str(song),
        "output": str(vocals_path),
        "model": str(separator_dir / MODEL),
    }
    return run_worker(
        request("separate", "p1", params) + request("shutdown", "s1"), timeout=SLOW_RUN_SECONDS
    )


def test_every_message_is_a_schema_valid_response(session: WorkerRun) -> None:
    assert all(is_valid("Response", m) for m in session.messages)


def test_the_worker_ends_with_a_separate_result(session: WorkerRun) -> None:
    assert session.messages[-2]["type"] == "result"


def test_progress_runs_from_zero_to_one(session: WorkerRun) -> None:
    ratios = [m["ratio"] for m in session.messages if m["type"] == "progress"]

    assert ratios == [0.0, 0.5, 1.0]


def test_the_result_is_eight_seconds_of_stereo(session: WorkerRun) -> None:
    assert session.messages[-2]["result"] == {
        "durationMs": 8000,
        "sampleRate": 44100,
        "channels": 2,
    }


def test_the_vocals_match_the_reference_stems(
    session: WorkerRun, separator_dir: Path, vocals_path: Path
) -> None:
    reference = _read_interleaved(separator_dir / REFERENCE_STEMS)
    snr = _snr_db(reference, decode_audio(vocals_path))
    print(f"separate end-to-end SNR: {snr:.2f} dB")  # noqa: T201

    assert snr >= MIN_SNR_DB, f"SNR {snr:.2f} dB is below {MIN_SNR_DB} dB"
