"""`refine` through the worker process with the real character CTC model and ffmpeg.

Skipped unless `LIRISYNC_ALIGNER_DIR` names a directory fetched with
`tools/fetch_aligner_model.py` and ffmpeg is installed. The audio is noise, not
singing, so only the shape of the answer is checked: that it fits the schema and
that each line gets the status its window calls for.
"""

import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from lirisync_worker.audio_io import encode_wav, ffmpeg_executable
from lirisync_worker.separation.stft import SAMPLE_RATE
from tests.medium.support import WorkerRun, is_valid, request, result_of, run_worker

ENV_VAR = "LIRISYNC_ALIGNER_DIR"
FILES = ("model.int8.onnx", "vocab.json")
SECONDS = 4
NOISE_AMPLITUDE = 0.01
# Loading the 360 MB model and decoding take a while on a slow machine.
TIMEOUT_SECONDS = 300


@pytest.fixture(scope="module")
def aligner_dir() -> Path:
    if shutil.which(ffmpeg_executable()) is None:
        pytest.skip("ffmpeg is not installed")
    value = os.environ.get(ENV_VAR)
    if not value:
        pytest.skip(f"{ENV_VAR} is not set; see tools/fetch_aligner_model.py")
    directory = Path(value).expanduser()
    missing = [name for name in FILES if not (directory / name).is_file()]
    if missing:
        pytest.skip(f"{ENV_VAR}={directory} lacks {missing}; see tools/fetch_aligner_model.py")
    return directory


@pytest.fixture(scope="module")
def session(aligner_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> WorkerRun:
    audio = tmp_path_factory.mktemp("refine-real") / "noise.wav"
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal((2, SECONDS * SAMPLE_RATE)) * NOISE_AMPLITUDE).astype(np.float32)
    encode_wav(noise, audio)
    params = {
        "audio": str(audio),
        "model": str(aligner_dir),
        "lyrics": ["風が吹く", "花", "雨", ""],
        "windows": [
            {"startMs": 500, "endMs": 3000},
            None,
            {"startMs": 60_000, "endMs": 61_000},
            None,
        ],
        "spelling": "kana",
        "ignored": [],
        "marginMs": 200,
    }
    return run_worker(
        request("refine", "r1", params) + request("shutdown", "s1"), timeout=TIMEOUT_SECONDS
    )


def test_every_line_is_a_schema_valid_response(session: WorkerRun) -> None:
    assert all(is_valid("Response", m) for m in session.messages)


def test_the_result_is_a_schema_valid_refine_result(session: WorkerRun) -> None:
    final = next(m for m in session.messages if m["type"] == "result")

    assert is_valid("RefineResult", result_of(final))


def test_each_line_gets_the_status_its_window_calls_for(session: WorkerRun) -> None:
    final = next(m for m in session.messages if m["type"] == "result")
    lines = result_of(final)["lines"]
    assert isinstance(lines, list)

    assert [line["status"] for line in lines] == ["refined", "no_window", "too_short", "no_window"]


def test_the_refined_line_lies_inside_its_window_with_margin(session: WorkerRun) -> None:
    final = next(m for m in session.messages if m["type"] == "result")
    lines = result_of(final)["lines"]
    assert isinstance(lines, list)
    first = lines[0]

    assert 300 <= first["startMs"] <= first["endMs"] <= 3200


def test_the_worker_exits_cleanly(session: WorkerRun) -> None:
    assert session.returncode == 0
