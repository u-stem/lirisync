"""The mask-estimation ONNX model and the vocal separation built on it.

The model takes the STFT of one 8 s stereo chunk as `spec` (float32,
`[1, 4, BINS, FRAMES]`: L.re, L.im, R.re, R.im) and returns a `mask` of the
same shape. The vocals are the inverse STFT of `spec * mask`, cut to the chunk
length, with the DC bin zeroed. `MaskModel` does this for one chunk, so it can
be handed to `demix` as its `process` callable.
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from lirisync_worker.separation.demix import Audio, demix
from lirisync_worker.separation.stft import (
    BINS,
    CHUNK,
    FRAMES,
    apply_mask,
    from_model_output,
    istft,
    stft,
    to_model_input,
)

INPUT_NAME = "spec"
OUTPUT_NAME = "mask"
MODEL_SHAPE = (1, 4, BINS, FRAMES)
CPU_PROVIDERS = ("CPUExecutionProvider",)


class Node(Protocol):
    """The part of an onnxruntime `NodeArg` that is checked."""

    @property
    def name(self) -> str: ...

    @property
    def shape(self) -> Sequence[Any]: ...


class Session(Protocol):
    """The part of an `onnxruntime.InferenceSession` that is used."""

    def get_inputs(self) -> Sequence[Node]: ...

    def get_outputs(self) -> Sequence[Node]: ...

    def run(
        self, output_names: Sequence[str] | None, input_feed: dict[str, npt.NDArray[np.float32]]
    ) -> Sequence[Any]: ...


SessionFactory = Callable[[str, Sequence[str]], Session]


def open_session(path: str, providers: Sequence[str]) -> Session:
    """Open `path` with onnxruntime (imported here so tests need not load it)."""
    import onnxruntime  # noqa: PLC0415 - heavy import, only when a real model is opened

    return onnxruntime.InferenceSession(path, providers=list(providers))


class MaskModel:
    """Vocal mask model: `[2, CHUNK]` float32 in, the vocal estimate `[2, CHUNK]` out."""

    def __init__(
        self,
        path: Path,
        providers: Sequence[str] = CPU_PROVIDERS,
        *,
        session_factory: SessionFactory = open_session,
    ) -> None:
        self._session = session_factory(str(path), providers)
        _check_contract(self._session, path)

    def __call__(self, chunk: Audio) -> Audio:
        if chunk.shape != (2, CHUNK):
            raise ValueError(f"chunk must have shape (2, {CHUNK}), got {chunk.shape}")
        spec = stft(chunk)
        outputs = self._session.run([OUTPUT_NAME], {INPUT_NAME: to_model_input(spec)})
        mask = outputs[0]
        if not isinstance(mask, np.ndarray):
            raise ValueError(f"model output must be an ndarray, got {type(mask).__name__}")
        if not np.isfinite(mask).all():
            raise ValueError("model output contains non-finite values (NaN or inf)")
        vocals = apply_mask(spec, from_model_output(mask))
        return istft(vocals, CHUNK)


def separate_vocals(audio: Audio, model: MaskModel) -> Audio:
    """Vocals of `[2, n]` 44.1 kHz stereo audio, same shape, via overlapped chunks."""
    return demix(audio, model)


def _check_contract(session: Session, path: Path) -> None:
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if [node.name for node in inputs] != [INPUT_NAME]:
        raise ValueError(
            f"{path}: expected one input named {INPUT_NAME!r}, got {[n.name for n in inputs]}"
        )
    if [node.name for node in outputs] != [OUTPUT_NAME]:
        raise ValueError(
            f"{path}: expected one output named {OUTPUT_NAME!r}, got {[n.name for n in outputs]}"
        )
    for node in (inputs[0], outputs[0]):
        if not _shape_fits(node.shape):
            raise ValueError(
                f"{path}: {node.name!r} has shape {list(node.shape)}, "
                f"expected {list(MODEL_SHAPE)} (dynamic dimensions allowed)"
            )


def _shape_fits(declared: Sequence[Any]) -> bool:
    """True when each static dimension equals the expected one; named or unknown ones pass."""
    if len(declared) != len(MODEL_SHAPE):
        return False
    return all(
        not isinstance(dim, int) or dim == expected
        for dim, expected in zip(declared, MODEL_SHAPE, strict=True)
    )
