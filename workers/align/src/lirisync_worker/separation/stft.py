"""STFT, iSTFT and the model's tensor layout, matching PyTorch's semantics.

The separation model works on the STFT of an 8 s stereo chunk at 44.1 kHz and
returns a complex mask of the same shape. The transforms are ours, so they
follow `torch.stft` / `torch.istft` (n_fft 2048, hop 441, periodic Hann window,
centered with reflect padding, one-sided, not normalized) to match the
pipeline the model was trained with.
"""

import numpy as np
import numpy.typing as npt

SAMPLE_RATE = 44100
N_FFT = 2048
HOP = 441
CHUNK = 8 * SAMPLE_RATE
FRAMES = 1 + CHUNK // HOP
BINS = N_FFT // 2 + 1

# Below this the overlap-added squared window is treated as zero (torch uses
# the same threshold in its non-overlap-add check).
_ENVELOPE_FLOOR = 1e-11

Wave = npt.NDArray[np.float32]
Spec = npt.NDArray[np.complex64]
ModelArray = npt.NDArray[np.float32]


def hann(n: int) -> npt.NDArray[np.float64]:
    """Periodic Hann window (the default of `torch.hann_window`)."""
    k = np.arange(n)
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * k / n)


def stft(x: npt.NDArray[np.floating]) -> Spec:
    """STFT of `[channels, samples]` into complex64 `[channels, BINS, frames]`.

    The signal is reflect-padded by `N_FFT // 2` on both sides (`center=True`),
    so the frame count is `1 + samples // HOP`. Inputs of `N_FFT // 2` samples
    or fewer are rejected, as in torch, whose reflect padding cannot cover them.
    """
    signal = np.asarray(x, dtype=np.float32)
    if signal.ndim != 2:  # noqa: PLR2004 - [channels, samples]
        raise ValueError(f"expected [channels, samples], got shape {signal.shape}")
    if signal.shape[-1] <= N_FFT // 2:
        raise ValueError(
            f"need more than {N_FFT // 2} samples for reflect padding, "
            f"got {signal.shape[-1]} samples"
        )
    padded = np.pad(signal, ((0, 0), (N_FFT // 2, N_FFT // 2)), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT, axis=-1)[:, ::HOP, :]
    windowed = frames * hann(N_FFT).astype(np.float32)
    spec = np.fft.rfft(windowed, axis=-1).astype(np.complex64)
    return np.ascontiguousarray(spec.transpose(0, 2, 1))


def istft(spec: npt.NDArray[np.complexfloating], length: int) -> Wave:
    """Inverse of `stft`, cut to `length` samples (like `torch.istft`).

    Each frame is inverse-transformed, windowed and overlap-added; the sum is
    divided by the overlap-added squared window, then the `N_FFT // 2` samples
    of centering padding are trimmed from the start. Where the envelope is
    ~0 the samples are left unnormalised instead of raising like torch; that
    cannot happen after trimming for these parameters.
    """
    channels, _, frame_count = spec.shape
    window = hann(N_FFT)
    frames = np.fft.irfft(np.asarray(spec, dtype=np.complex128).transpose(0, 2, 1), n=N_FFT)
    frames = frames * window

    total = (frame_count - 1) * HOP + N_FFT
    signal = np.zeros((channels, total))
    envelope = np.zeros(total)
    squared = window * window
    for t in range(frame_count):
        start = t * HOP
        signal[:, start : start + N_FFT] += frames[:, t, :]
        envelope[start : start + N_FFT] += squared

    voiced = envelope > _ENVELOPE_FLOOR
    signal[:, voiced] /= envelope[voiced]

    trimmed = signal[:, N_FFT // 2 : N_FFT // 2 + length]
    out = np.zeros((channels, length), dtype=np.float32)
    out[:, : trimmed.shape[1]] = trimmed
    return out


def to_model_input(spec: npt.NDArray[np.complexfloating]) -> ModelArray:
    """Pack a stereo spectrogram into the model layout `[1, 4, BINS, FRAMES]`.

    Plane order: L.re, L.im, R.re, R.im.
    """
    if spec.shape != (2, BINS, FRAMES):
        raise ValueError(f"expected spectrogram of shape {(2, BINS, FRAMES)}, got {spec.shape}")
    planes = np.stack([spec[0].real, spec[0].imag, spec[1].real, spec[1].imag])
    return planes.astype(np.float32)[np.newaxis]


def from_model_output(arr: npt.NDArray[np.floating]) -> Spec:
    """Unpack the model layout `[1, 4, BINS, FRAMES]` into `[2, BINS, FRAMES]` complex64."""
    if arr.shape != (1, 4, BINS, FRAMES):
        raise ValueError(f"expected model array of shape {(1, 4, BINS, FRAMES)}, got {arr.shape}")
    planes = np.asarray(arr[0], dtype=np.float32)
    spec = np.empty((2, BINS, FRAMES), dtype=np.complex64)
    spec.real = planes[0::2]
    spec.imag = planes[1::2]
    return spec


def apply_mask(
    spec: npt.NDArray[np.complexfloating], mask: npt.NDArray[np.complexfloating]
) -> Spec:
    """Complex-multiply `spec` by `mask` and zero the DC bin.

    Zeroing frequency 0 mirrors the reference model's `zero_dc` option.
    """
    if spec.shape[:2] != (2, BINS) or mask.shape != spec.shape:
        raise ValueError(
            f"spec and mask must share the shape (2, {BINS}, frames), "
            f"got {spec.shape} and {mask.shape}"
        )
    out = (spec * mask).astype(np.complex64)
    out[:, 0, :] = 0
    return out
