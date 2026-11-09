import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.separation.stft import (
    BINS,
    CHUNK,
    FRAMES,
    HOP,
    N_FFT,
    SAMPLE_RATE,
    apply_mask,
    from_model_output,
    hann,
    istft,
    stft,
    to_model_input,
)


def _random_stereo(samples: int, seed: int = 0) -> npt.NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    return rng.uniform(-1.0, 1.0, size=(2, samples)).astype(np.float32)


def _random_spec(seed: int = 0) -> npt.NDArray[np.complex64]:
    rng = np.random.default_rng(seed)
    shape = (2, BINS, FRAMES)
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(np.complex64)


def test_chunk_is_eight_seconds() -> None:
    assert CHUNK == 8 * SAMPLE_RATE


def test_chunk_gives_the_model_frame_count() -> None:
    assert 1 + CHUNK // HOP == FRAMES


def test_bins_are_half_the_fft_size_plus_one() -> None:
    assert N_FFT // 2 + 1 == BINS


def test_hann_is_periodic() -> None:
    np.testing.assert_allclose(hann(4), [0.0, 0.5, 1.0, 0.5], atol=1e-12)


def test_hann_of_eight_peaks_at_the_middle() -> None:
    assert hann(8)[4] == 1.0


def test_stft_shape_for_a_model_chunk() -> None:
    assert stft(_random_stereo(CHUNK)).shape == (2, BINS, FRAMES)


def test_stft_is_complex64() -> None:
    assert stft(_random_stereo(CHUNK)).dtype == np.complex64


def test_stft_frame_count_follows_samples_over_hop() -> None:
    assert stft(_random_stereo(5000)).shape[2] == 1 + 5000 // HOP


def test_stft_of_a_sine_peaks_in_the_expected_bin() -> None:
    target_bin = 100
    t = np.arange(CHUNK) / SAMPLE_RATE
    sine = np.sin(2 * np.pi * target_bin * SAMPLE_RATE / N_FFT * t).astype(np.float32)
    spec = stft(np.stack([sine, sine]))
    assert int(np.argmax(np.abs(spec[0, :, FRAMES // 2]))) == target_bin


def test_stft_matches_the_definition_for_one_frame() -> None:
    x = _random_stereo(5000)
    padded = np.pad(x[0].astype(np.float64), N_FFT // 2, mode="reflect")
    frame = padded[3 * HOP : 3 * HOP + N_FFT] * hann(N_FFT)
    expected = np.fft.rfft(frame)
    np.testing.assert_allclose(stft(x)[0, :, 3], expected, atol=1e-3)


def test_istft_inverts_stft_for_a_model_chunk() -> None:
    x = _random_stereo(CHUNK)
    np.testing.assert_allclose(istft(stft(x), CHUNK), x, atol=1e-5)


def test_istft_inverts_stft_for_an_odd_length() -> None:
    x = _random_stereo(12345, seed=1)
    np.testing.assert_allclose(istft(stft(x), 12345), x, atol=1e-5)


def test_istft_returns_the_requested_length() -> None:
    assert istft(stft(_random_stereo(12345)), 12345).shape == (2, 12345)


def test_istft_is_float32() -> None:
    assert istft(stft(_random_stereo(5000)), 5000).dtype == np.float32


def test_model_input_layout_is_batch_of_four_planes() -> None:
    assert to_model_input(_random_spec()).shape == (1, 4, BINS, FRAMES)


def test_model_input_is_float32() -> None:
    assert to_model_input(_random_spec()).dtype == np.float32


def test_model_input_channel_order_starts_with_left_real() -> None:
    spec = _random_spec()
    np.testing.assert_array_equal(to_model_input(spec)[0, 0], spec[0].real)


def test_model_input_channel_order_has_left_imag_second() -> None:
    spec = _random_spec()
    np.testing.assert_array_equal(to_model_input(spec)[0, 1], spec[0].imag)


def test_model_input_channel_order_has_right_real_third() -> None:
    spec = _random_spec()
    np.testing.assert_array_equal(to_model_input(spec)[0, 2], spec[1].real)


def test_model_input_channel_order_ends_with_right_imag() -> None:
    spec = _random_spec()
    np.testing.assert_array_equal(to_model_input(spec)[0, 3], spec[1].imag)


def test_model_layout_round_trips() -> None:
    spec = _random_spec()
    np.testing.assert_array_equal(from_model_output(to_model_input(spec)), spec)


def test_stft_rejects_a_one_dimensional_signal() -> None:
    signal = np.zeros(CHUNK, dtype=np.float32)

    with pytest.raises(ValueError, match="channels, samples"):
        stft(signal)


def test_model_input_rejects_a_mono_spectrogram() -> None:
    mono = np.zeros((1, BINS, FRAMES), dtype=np.complex64)

    with pytest.raises(ValueError, match="shape"):
        to_model_input(mono)


def test_model_output_rejects_a_missing_batch_axis() -> None:
    unbatched = np.zeros((4, BINS, FRAMES), dtype=np.float32)

    with pytest.raises(ValueError, match="shape"):
        from_model_output(unbatched)


def test_model_output_is_complex64_stereo() -> None:
    out = from_model_output(to_model_input(_random_spec()))
    assert (out.dtype.type, out.shape) == (np.complex64, (2, BINS, FRAMES))


def test_apply_mask_zeroes_the_dc_bin() -> None:
    spec = _random_spec(0)
    mask = _random_spec(1)
    assert not apply_mask(spec, mask)[:, 0, :].any()


def test_apply_mask_multiplies_the_other_bins() -> None:
    spec = _random_spec(0)
    mask = _random_spec(1)
    np.testing.assert_allclose(apply_mask(spec, mask)[:, 1:, :], (spec * mask)[:, 1:, :])


def _reference_frame(x: npt.NDArray[np.float32], index: int) -> npt.NDArray[np.complex128]:
    padded = np.pad(x[0].astype(np.float64), N_FFT // 2, mode="reflect")
    return np.fft.rfft(padded[index * HOP : index * HOP + N_FFT] * hann(N_FFT))


def test_stft_first_frame_sees_reflect_padding() -> None:
    x = _random_stereo(5000)
    np.testing.assert_allclose(stft(x)[0, :, 0], _reference_frame(x, 0), atol=1e-3)


def test_stft_last_frame_sees_reflect_padding() -> None:
    x = _random_stereo(5000)
    last = 5000 // HOP
    np.testing.assert_allclose(stft(x)[0, :, last], _reference_frame(x, last), atol=1e-3)


def test_stft_rejects_input_no_longer_than_the_padding() -> None:
    with pytest.raises(ValueError, match="samples"):
        stft(_random_stereo(N_FFT // 2))


def test_stft_accepts_input_one_sample_longer_than_the_padding() -> None:
    assert stft(_random_stereo(N_FFT // 2 + 1)).shape == (2, BINS, 1 + (N_FFT // 2 + 1) // HOP)


def test_apply_mask_rejects_a_mask_with_another_frame_count() -> None:
    with pytest.raises(ValueError, match="shape"):
        apply_mask(_random_spec(), _random_spec()[:, :, :-1])


def test_apply_mask_rejects_a_mono_spectrogram() -> None:
    spec = _random_spec()[:1]
    with pytest.raises(ValueError, match="shape"):
        apply_mask(spec, spec)


def test_apply_mask_rejects_a_spectrogram_with_the_wrong_bin_count() -> None:
    spec = _random_spec()[:, :-1, :]
    with pytest.raises(ValueError, match="shape"):
        apply_mask(spec, spec)
