"""Overlapped chunked inference with a cross-fade, around a per-chunk callable.

Follows the reference demix of the Music-Source-Separation-Training repository
(utils/model_utils.py, MIT): the input is cut into overlapping chunks, each
chunk goes through `process`, and the outputs are blended with a window that
fades linearly at both ends so chunk seams do not click.
"""

from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from lirisync_worker.separation.stft import CHUNK

Audio = npt.NDArray[np.float32]

STEREO = 2
# Below two chunks per position, adjacent faded windows do not overlap and the
# seams would come out as 0.
MIN_OVERLAP = 2


def fade_length(chunk: int) -> int:
    """Fade length at each end of a chunk window: a tenth of the chunk."""
    return chunk // 10


def fade_window(chunk: int, fade: int) -> Audio:
    """Ones with a linear fade-in over `fade` samples and a fade-out over the last `fade`."""
    window = np.ones(chunk, dtype=np.float32)
    if fade > 0:
        window[:fade] = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        window[-fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return window


def chunk_count(samples: int, chunk: int = CHUNK, overlap: int = 2) -> int:
    """How many times `demix` calls `process` for `samples` samples of input.

    Raises `ValueError` for an `overlap` that `demix` rejects.
    """
    if overlap < MIN_OVERLAP or chunk // overlap < 1:
        raise ValueError(f"need 2 <= overlap <= chunk, got overlap={overlap}, chunk={chunk}")
    step = chunk // overlap
    border = chunk - step
    total = samples + 2 * border if samples > 2 * border and border > 0 else samples
    return -(-total // step)


def demix(
    audio: Audio,
    process: Callable[[Audio], Audio],
    chunk: int = CHUNK,
    overlap: int = 2,
) -> Audio:
    """Run `process` over overlapping chunks of `[2, n]` audio and blend the results.

    `process` always receives exactly `[2, chunk]` and returns the same shape.
    A tail chunk shorter than `chunk` is reflect-padded when it is longer than
    half a chunk, zero-padded otherwise. The first chunk has no fade-in and the
    last chunk has no fade-out. Inputs longer than twice the border
    (`chunk - chunk // overlap`) are reflect-padded by the border first and the
    padding is removed at the end. Samples no window covers come out as 0.
    Raises `ValueError` if `audio` is not `[2, n]`, if `overlap` is below 2
    (without overlap the faded seams would come out as 0) or leaves no step,
    and if `process` does not return an ndarray of shape `[2, chunk]`.
    """
    _check_arguments(audio, chunk, overlap)
    step = chunk // overlap
    border = chunk - step
    fade = fade_length(chunk)
    base_window = fade_window(chunk, fade)

    length = audio.shape[-1]
    padded = audio
    if length > 2 * border and border > 0:
        padded = np.pad(audio, ((0, 0), (border, border)), mode="reflect")
    total = padded.shape[-1]

    result = np.zeros(padded.shape, dtype=np.float32)
    counter = np.zeros(total, dtype=np.float32)

    for start in range(0, total, step):
        part = padded[:, start : start + chunk]
        part_len = part.shape[-1]
        if part_len < chunk:
            missing = ((0, 0), (0, chunk - part_len))
            if part_len > chunk // 2:
                part = np.pad(part, missing, mode="reflect")
            else:
                part = np.pad(part, missing, mode="constant")

        # A contiguous copy: `process` may mutate its input, and `part` can be a
        # view of the caller's audio.
        part = part.copy()

        window = base_window.copy()
        if fade > 0:
            if start == 0:
                window[:fade] = 1.0
            if start + step >= total:
                window[-fade:] = 1.0

        returned = process(part)
        if not isinstance(returned, np.ndarray):
            raise ValueError(f"process must return an ndarray, got {type(returned).__name__}")
        if returned.shape != (STEREO, chunk):
            raise ValueError(f"process must return shape (2, {chunk}), got {returned.shape}")
        out = returned.astype(np.float32, copy=False)
        end = start + part_len
        result[:, start:end] += out[:, :part_len] * window[:part_len]
        counter[start:end] += window[:part_len]

    # In place, to avoid a second full-size array. Samples no window covers
    # (counter 0) are left as they are, which is 0, and NaN becomes 0.
    blended: Audio = result
    np.divide(blended, counter, out=blended, where=counter != 0)
    np.nan_to_num(blended, copy=False, nan=0.0)

    if length > 2 * border and border > 0:
        blended = blended[:, border:-border]
    return blended


def _check_arguments(audio: Audio, chunk: int, overlap: int) -> None:
    if audio.ndim != 2 or audio.shape[0] != STEREO:  # noqa: PLR2004 - [channels, samples]
        raise ValueError(f"audio must have shape (2, samples), got {audio.shape}")
    if overlap < MIN_OVERLAP or chunk // overlap < 1:
        raise ValueError(f"need 2 <= overlap <= chunk, got overlap={overlap}, chunk={chunk}")
