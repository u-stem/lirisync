"""The character CTC model: audio in, per-frame log-probabilities out.

The model (a wav2vec2 CTC head exported to ONNX) takes `input_values`
(float32, `[batch, samples]`), 16 kHz mono audio normalized to zero mean and
unit variance, and returns `logits` (`[batch, frames, V]`). A frame looks at 400
samples and the frames are 320 samples (20 ms) apart, so n samples give
`(n - 400) // 320 + 1` frames and at least 400 samples are needed (frame k
covers samples 320 * k to 320 * k + 400). Id 0 is the CTC blank.
`CharCtcModel.log_probs` returns the log-softmax of the logits, ready for
`ctc_align.align_ctc`, together with `vocab`, the one-character tokens that
`ctc_tokens` spells lyrics with.

The directory holds `model.int8.onnx` and `vocab.json` (see
`tools/fetch_aligner_model.py`).
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from pydantic import StrictInt, TypeAdapter, ValidationError

from lirisync_worker.ctc_tokens import CharVocab

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
FRAME_MS = 20
BLANK = 0
MIN_SAMPLES = 400

MODEL_FILE = "model.int8.onnx"
VOCAB_FILE = "vocab.json"
INPUT_NAME = "input_values"
OUTPUT_NAME = "logits"
CPU_PROVIDERS = ("CPUExecutionProvider",)

# Same as the Wav2Vec2FeatureExtractor: (x - mean) / sqrt(var + eps).
_NORMALIZATION_EPS = 1e-7
_INPUT_RANK = 2
_LOGITS_RANK = 3

Audio = npt.NDArray[np.float32]
LogProbs = npt.NDArray[np.float32]

_VOCAB_SCHEMA = TypeAdapter(dict[str, StrictInt])


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
        self, output_names: Sequence[str] | None, input_feed: dict[str, Audio]
    ) -> Sequence[Any]: ...


SessionFactory = Callable[[str, Sequence[str]], Session]


def open_session(path: str, providers: Sequence[str]) -> Session:
    """Open `path` with onnxruntime (imported here so tests need not load it)."""
    import onnxruntime  # noqa: PLC0415 - heavy import, only when a real model is opened

    return onnxruntime.InferenceSession(path, providers=list(providers))


def parse_vocab(raw: object, source: str) -> dict[str, int]:
    """A token-to-id map with unique, non-negative ids that include the blank id."""
    try:
        vocab = _VOCAB_SCHEMA.validate_python(raw, strict=True)
    except ValidationError as error:
        raise ValueError(f"{source}: vocab must map tokens to integer ids: {error}") from error
    ids = list(vocab.values())
    if len(set(ids)) != len(ids):
        raise ValueError(f"{source}: duplicate ids in vocab")
    if any(token_id < 0 for token_id in ids):
        raise ValueError(f"{source}: negative id in vocab")
    if BLANK not in ids:
        raise ValueError(f"{source}: vocab has no entry for the blank id {BLANK}")
    return vocab


def _read_vocab(path: Path) -> dict[str, int]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: vocab is not valid JSON: {error}") from error
    return parse_vocab(raw, str(path))


class CharCtcModel:
    """Character CTC model: 16 kHz mono float32 in, `[frames, V]` log-probabilities out."""

    def __init__(
        self,
        model_dir: Path,
        providers: Sequence[str] = CPU_PROVIDERS,
        *,
        session_factory: SessionFactory = open_session,
    ) -> None:
        vocab = _read_vocab(model_dir / VOCAB_FILE)
        self._max_id = max(vocab.values())
        self.vocab = CharVocab(vocab)
        self._session = session_factory(str(model_dir / MODEL_FILE), providers)
        _check_contract(self._session, model_dir / MODEL_FILE, self._max_id)

    def log_probs(self, audio: Audio) -> LogProbs:
        """Log-softmax over the vocabulary for each 20 ms frame of `audio`."""
        _check_audio(audio)
        outputs = self._session.run([OUTPUT_NAME], {INPUT_NAME: _normalize(audio)[np.newaxis, :]})
        logits = outputs[0]
        if not isinstance(logits, np.ndarray):
            raise ValueError(f"model output must be an ndarray, got {type(logits).__name__}")
        frames = frame_count(audio.shape[0])
        if logits.ndim != _LOGITS_RANK or logits.shape[0] != 1:
            raise ValueError(f"model output has shape {logits.shape}, expected (1, frames, V)")
        if logits.shape[1] != frames:
            raise ValueError(f"model output has {logits.shape[1]} frames, expected {frames}")
        if logits.shape[2] <= self._max_id:
            raise ValueError(
                f"model output has {logits.shape[2]} columns, "
                f"but the vocabulary has ids up to {self._max_id}"
            )
        if not np.isfinite(logits).all():
            raise ValueError("model output contains non-finite values (NaN or inf)")
        return _log_softmax(logits[0].astype(np.float32, copy=False))


def frame_count(samples: int) -> int:
    """How many frames the model emits for `samples` samples (at least `MIN_SAMPLES`)."""
    return (samples - MIN_SAMPLES) // FRAME_SAMPLES + 1


def _check_audio(audio: object) -> None:
    if not isinstance(audio, np.ndarray) or audio.ndim != 1:
        raise ValueError("audio must be a 1-D numpy array (16 kHz mono)")
    if audio.dtype != np.float32:
        raise ValueError(f"audio must be float32, got {audio.dtype}")
    if audio.shape[0] < MIN_SAMPLES:
        raise ValueError(f"audio must have at least {MIN_SAMPLES} samples, got {audio.shape[0]}")
    if not np.isfinite(audio).all():
        raise ValueError("audio contains non-finite values (NaN or inf)")


def _normalize(audio: Audio) -> Audio:
    """Zero mean and unit variance; a constant clip becomes zeros, not NaN."""
    wide = audio.astype(np.float64)
    normalized = (wide - float(wide.mean())) / np.sqrt(float(wide.var()) + _NORMALIZATION_EPS)
    return np.asarray(normalized, dtype=np.float32)


def _log_softmax(logits: LogProbs) -> LogProbs:
    shifted = logits - logits.max(axis=1, keepdims=True)
    log_probs: LogProbs = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    return log_probs


def _check_contract(session: Session, path: Path, max_id: int) -> None:
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
    if len(inputs[0].shape) != _INPUT_RANK:
        raise ValueError(
            f"{path}: {INPUT_NAME!r} has shape {list(inputs[0].shape)}, expected [batch, samples]"
        )
    shape = outputs[0].shape
    if len(shape) != _LOGITS_RANK:
        raise ValueError(
            f"{path}: {OUTPUT_NAME!r} has shape {list(shape)}, expected [batch, frames, V]"
        )
    columns = shape[-1]
    if isinstance(columns, int) and columns <= max_id:
        raise ValueError(
            f"{path}: {OUTPUT_NAME!r} has {columns} columns, "
            f"but the vocabulary has ids up to {max_id}"
        )
