"""Check the real separation model against the reference output shipped with it.

The model files are not in the repository, so CI skips these tests. Run them
by hand after changing anything under `separation/`:

    uv --directory workers/align run python tools/fetch_separator_model.py --dest DIR
    LIRISYNC_SEPARATOR_DIR=DIR uv --directory workers/align run pytest \
        tests/medium/test_separator_reference.py

Run them on Windows too, and record the SNR in the pull request (not in a file).
"""

import os
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.separation.model import MaskModel, separate_vocals
from lirisync_worker.separation.stft import CHUNK

ENV_VAR = "LIRISYNC_SEPARATOR_DIR"
MODEL = "sep-all-int8.onnx"
REFERENCE_INPUT = "ref-input.f32"
REFERENCE_STEMS = "ref-stems-all-int8.f32"

# The model card says the int8 model is exact on AVX512-VNNI and AVX-VNNI CPUs
# and may saturate on older x86 CPUs without VNNI (not measured upstream).
# 47.5 dB was measured here on Apple silicon. 40 dB is a floor, not a target: it
# separates "the port is right" from a layout, STFT or mask bug, which gives
# close to 0 dB. A CPU that falls between the two needs a look, not a lower bar.
MIN_SNR_DB = 40.0
# The first half of an 8 s input is covered by the first chunk alone (no
# fade-in, and the second chunk starts at the half), so the blended result
# there is that chunk's output unchanged.
MIN_FIRST_HALF_SNR_DB = 60.0

Audio = npt.NDArray[np.float32]


@pytest.fixture(scope="module")
def separator_dir() -> Path:
    value = os.environ.get(ENV_VAR)
    if not value:
        pytest.skip(f"{ENV_VAR} is not set; see tools/fetch_separator_model.py")
    directory = Path(value).expanduser()
    missing = [
        n for n in (MODEL, REFERENCE_INPUT, REFERENCE_STEMS) if not (directory / n).is_file()
    ]
    if missing:
        pytest.skip(f"{ENV_VAR}={directory} lacks {missing}; see tools/fetch_separator_model.py")
    return directory


@pytest.fixture(scope="module")
def model(separator_dir: Path) -> MaskModel:
    return MaskModel(separator_dir / MODEL)


@pytest.fixture(scope="module")
def reference_input(separator_dir: Path) -> Audio:
    return _read_interleaved(separator_dir / REFERENCE_INPUT)


@pytest.fixture(scope="module")
def reference_stems(separator_dir: Path) -> Audio:
    return _read_interleaved(separator_dir / REFERENCE_STEMS)


@pytest.fixture(scope="module")
def single_chunk_output(model: MaskModel, reference_input: Audio) -> Audio:
    return model(reference_input)


def _read_interleaved(path: Path) -> Audio:
    """Interleaved little-endian float32 frames into `[2, n]`."""
    samples = np.fromfile(path, dtype="<f4")
    return np.ascontiguousarray(samples.reshape(-1, 2).T, dtype=np.float32)


def _snr_db(reference: Audio, estimate: Audio) -> float:
    signal = float(np.sum(reference.astype(np.float64) ** 2))
    noise = float(np.sum((reference.astype(np.float64) - estimate.astype(np.float64)) ** 2))
    if noise == 0.0:
        return float("inf")
    return 10.0 * float(np.log10(signal / noise))


def test_reference_input_is_one_stereo_chunk(reference_input: Audio) -> None:
    assert reference_input.shape == (2, CHUNK)


def test_model_output_matches_the_reference_stems(
    single_chunk_output: Audio, reference_stems: Audio
) -> None:
    snr = _snr_db(reference_stems, single_chunk_output)

    assert snr >= MIN_SNR_DB, f"SNR {snr:.2f} dB is below {MIN_SNR_DB} dB"


def test_blended_output_equals_the_single_chunk_output_where_one_chunk_covers_it(
    model: MaskModel, reference_input: Audio, single_chunk_output: Audio
) -> None:
    half = CHUNK // 2

    blended = separate_vocals(reference_input, model)
    snr = _snr_db(single_chunk_output[:, :half], blended[:, :half])

    assert snr >= MIN_FIRST_HALF_SNR_DB, f"SNR {snr:.2f} dB is below {MIN_FIRST_HALF_SNR_DB} dB"
