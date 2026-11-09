from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.separation.demix import chunk_count, demix, fade_length, fade_window
from lirisync_worker.separation.stft import CHUNK

SMALL = 100  # chunk length for most tests: step 50, border 50, fade 10


def _random_stereo(samples: int, seed: int = 0) -> npt.NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    return rng.uniform(-1.0, 1.0, size=(2, samples)).astype(np.float32)


def _identity(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    return part


def test_fade_window_matches_the_reference_example() -> None:
    expected = [0.0, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 0.0]
    np.testing.assert_allclose(fade_window(10, 3), expected)


def test_fade_window_is_float32() -> None:
    assert fade_window(10, 3).dtype == np.float32


def test_fade_window_without_a_fade_is_all_ones() -> None:
    np.testing.assert_array_equal(fade_window(8, 0), np.ones(8))


@pytest.mark.parametrize(
    "samples",
    [30, 49, 50, 51, 80, 99, 100, 101, 150, 230, 251, 333],
    ids=lambda n: f"n={n}",
)
def test_identity_process_reconstructs_the_input(samples: int) -> None:
    audio = _random_stereo(samples)
    np.testing.assert_allclose(demix(audio, _identity, chunk=SMALL), audio, atol=1e-6)


def test_identity_process_reconstructs_audio_shorter_than_a_model_chunk() -> None:
    audio = _random_stereo(1000)
    np.testing.assert_allclose(demix(audio, _identity), audio, atol=1e-6)


def test_identity_process_reconstructs_with_three_way_overlap() -> None:
    audio = _random_stereo(400)
    np.testing.assert_allclose(demix(audio, _identity, chunk=SMALL, overlap=3), audio, atol=1e-6)


def test_output_has_the_input_shape() -> None:
    assert demix(_random_stereo(333), _identity, chunk=SMALL).shape == (2, 333)


def test_output_is_float32() -> None:
    assert demix(_random_stereo(333), _identity, chunk=SMALL).dtype == np.float32


def test_process_receives_exact_model_chunks() -> None:
    shapes: list[tuple[int, ...]] = []

    def record(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        shapes.append(part.shape)
        return part

    demix(_random_stereo(1000), record)
    assert shapes == [(2, CHUNK)]


def test_process_receives_exact_chunks_for_small_chunk_size() -> None:
    shapes: set[tuple[int, ...]] = set()

    def record(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        shapes.add(part.shape)
        return part

    demix(_random_stereo(333), record, chunk=SMALL)
    assert shapes == {(2, SMALL)}


def test_a_half_gain_process_halves_the_output() -> None:
    audio = _random_stereo(333)
    result = demix(audio, lambda part: part * np.float32(0.5), chunk=SMALL)
    np.testing.assert_allclose(result, audio * 0.5, atol=1e-6)


def _count_calls(samples: int) -> int:
    calls = 0

    def count(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        nonlocal calls
        calls += 1
        return part

    demix(_random_stereo(samples), count, chunk=SMALL)
    return calls


def test_input_of_exactly_two_borders_is_not_padded() -> None:
    assert _count_calls(100) == 2


def test_input_longer_than_two_borders_is_reflect_padded() -> None:
    assert _count_calls(101) == 5


def test_a_remainder_longer_than_half_a_chunk_is_reflect_padded() -> None:
    parts: list[npt.NDArray[np.float32]] = []
    audio = _random_stereo(80)

    def record(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        parts.append(part)
        return part

    demix(audio, record, chunk=SMALL)
    np.testing.assert_array_equal(parts[0][:, 80:], audio[:, 78:58:-1])


def test_a_remainder_of_half_a_chunk_or_less_is_zero_padded() -> None:
    parts: list[npt.NDArray[np.float32]] = []

    def record(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        parts.append(part)
        return part

    demix(_random_stereo(50), record, chunk=SMALL)
    assert not parts[0][:, 50:].any()


def test_a_single_chunk_has_no_fade_at_either_end() -> None:
    audio = np.ones((2, SMALL), dtype=np.float32)
    np.testing.assert_allclose(demix(audio, _identity, chunk=SMALL), audio)


@pytest.mark.parametrize("overlap", [0, 1, SMALL + 1])
def test_demix_rejects_an_overlap_that_leaves_gaps_or_no_step(overlap: int) -> None:
    audio = np.ones((2, 400), dtype=np.float32)

    with pytest.raises(ValueError, match="overlap"):
        demix(audio, _identity, chunk=SMALL, overlap=overlap)


@pytest.mark.parametrize("shape", [(400,), (1, 400), (3, 400)])
def test_demix_rejects_audio_that_is_not_stereo(shape: tuple[int, ...]) -> None:
    audio = np.ones(shape, dtype=np.float32)

    with pytest.raises(ValueError, match="audio must have shape"):
        demix(audio, _identity, chunk=SMALL)


def test_the_first_chunk_has_no_fade_in() -> None:
    # Only the first chunk covers sample 0 (a faded window would give 0/0 -> 0).
    audio = np.ones((2, 400), dtype=np.float32)
    assert demix(audio, _identity, chunk=SMALL)[0, 0] == 1.0


def test_nan_from_the_process_becomes_zero() -> None:
    audio = np.ones((2, 400), dtype=np.float32)
    result = demix(audio, lambda part: part * np.float32("nan"), chunk=SMALL)
    assert not np.isnan(result).any()


def test_default_fade_is_a_tenth_of_the_model_chunk() -> None:
    assert fade_length(CHUNK) == 35280


def _scaled_by_call_index(
    calls: list[int],
) -> Callable[[npt.NDArray[np.float32]], npt.NDArray[np.float32]]:
    def process(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        calls.append(len(calls) + 1)
        return part * np.float32(calls[-1])

    return process


def test_blend_at_the_fade_in_seam_follows_the_linear_weights() -> None:
    # 100 samples, chunk 100: chunk 1 covers 0..99 (weight 1 up to sample 89),
    # chunk 2 starts at 50 with a 10-sample fade-in (weights j / 9).
    audio = np.ones((2, SMALL), dtype=np.float32)
    result = demix(audio, _scaled_by_call_index([]), chunk=SMALL)
    expected = [(1 + 2 * (j / 9)) / (1 + j / 9) for j in range(10)]
    np.testing.assert_allclose(result[0, 50:60], expected, rtol=1e-5)


def test_blend_at_the_fade_out_seam_follows_the_linear_weights() -> None:
    # Chunk 1 fades out over samples 90..99 (weights 1 - j / 9); chunk 2 has no fade-out.
    audio = np.ones((2, SMALL), dtype=np.float32)
    result = demix(audio, _scaled_by_call_index([]), chunk=SMALL)
    expected = [((1 - j / 9) + 2) / ((1 - j / 9) + 1) for j in range(10)]
    np.testing.assert_allclose(result[0, 90:100], expected, rtol=1e-5)


def test_blend_before_the_seam_is_only_the_first_chunk() -> None:
    audio = np.ones((2, SMALL), dtype=np.float32)
    result = demix(audio, _scaled_by_call_index([]), chunk=SMALL)
    np.testing.assert_allclose(result[0, :50], np.ones(50))


def test_blend_between_the_seams_is_a_plain_average() -> None:
    audio = np.ones((2, SMALL), dtype=np.float32)
    result = demix(audio, _scaled_by_call_index([]), chunk=SMALL)
    np.testing.assert_allclose(result[0, 60:90], np.full(30, 1.5), rtol=1e-5)


def test_process_returning_the_wrong_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="shape"):
        demix(_random_stereo(80), lambda part: part[:, :-1], chunk=SMALL)


def test_process_returning_a_mono_array_is_rejected() -> None:
    with pytest.raises(ValueError, match="shape"):
        demix(_random_stereo(80), lambda part: part[:1], chunk=SMALL)


def test_process_returning_a_non_array_is_rejected() -> None:
    with pytest.raises(ValueError, match="ndarray"):
        demix(_random_stereo(80), lambda part: part.tolist(), chunk=SMALL)


def test_a_process_that_mutates_its_input_leaves_the_callers_audio_intact() -> None:
    audio = _random_stereo(SMALL)
    original = audio.copy()

    def wipe(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        part[:] = 0.0
        return part

    demix(audio, wipe, chunk=SMALL)
    np.testing.assert_array_equal(audio, original)


def test_a_process_that_mutates_its_input_does_not_corrupt_later_chunks() -> None:
    audio = _random_stereo(SMALL)
    seen: list[npt.NDArray[np.float32]] = []

    def wipe_and_record(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        seen.append(part.copy())
        part[:] = 0.0
        return part

    demix(audio, wipe_and_record, chunk=SMALL)
    np.testing.assert_array_equal(seen[1][:, :50], audio[:, 50:])


@pytest.mark.parametrize(
    "samples",
    [1, 49, 50, 51, 99, 100, 101, 150, 199, 200, 201, 230, 251, 333, 1000],
    ids=lambda n: f"n={n}",
)
def test_chunk_count_equals_the_number_of_process_calls(samples: int) -> None:
    calls: list[int] = []

    def counting(part: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        calls.append(1)
        return part

    demix(_random_stereo(samples), counting, chunk=SMALL)

    assert chunk_count(samples, chunk=SMALL) == len(calls)


def test_chunk_count_of_no_samples_is_zero() -> None:
    assert chunk_count(0, chunk=SMALL) == 0


def test_chunk_count_rejects_an_overlap_below_two() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_count(10, chunk=SMALL, overlap=1)


def test_chunk_count_of_eight_seconds_at_the_default_chunk_is_two() -> None:
    assert chunk_count(CHUNK) == 2
