from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.separation.model import MaskModel, Session, separate_vocals
from lirisync_worker.separation.stft import BINS, CHUNK, FRAMES, SAMPLE_RATE, istft, stft

MODEL_SHAPE = [1, 4, BINS, FRAMES]
# Dropping the DC bin disturbs the first and last frames, whose reflect padding
# gives them a non-zero mean; the interior is unaffected.
EDGE = 4096
Feed = dict[str, npt.NDArray[np.float32]]
MaskFn = Callable[[npt.NDArray[np.float32]], npt.NDArray[np.float32]]


@dataclass(frozen=True)
class FakeNode:
    name: str
    shape: Sequence[int | str | None]


@dataclass
class FakeSession:
    """Stands in for an onnxruntime session; `mask_fn` maps the spec to the mask."""

    mask_fn: MaskFn
    inputs: list[FakeNode] = field(default_factory=lambda: [FakeNode("spec", MODEL_SHAPE)])
    outputs: list[FakeNode] = field(default_factory=lambda: [FakeNode("mask", MODEL_SHAPE)])
    feeds: list[Feed] = field(default_factory=list)

    def get_inputs(self) -> Sequence[FakeNode]:
        return self.inputs

    def get_outputs(self) -> Sequence[FakeNode]:
        return self.outputs

    def run(
        self, output_names: Sequence[str] | None, input_feed: Feed
    ) -> list[npt.NDArray[np.float32]]:
        self.feeds.append(input_feed)
        return [self.mask_fn(input_feed["spec"])]


def _ones_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    mask = np.zeros_like(spec)
    mask[:, 0::2] = 1.0  # real planes of L and R
    return mask


def _zero_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    return np.zeros_like(spec)


def _rotating_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    mask = np.zeros_like(spec)
    mask[:, 1::2] = 1.0  # imaginary planes of L and R: the mask is 1j everywhere
    return mask


def _nan_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    mask = _ones_mask(spec)
    mask[0, 0, 5, 5] = np.nan
    return mask


def _inf_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    mask = _ones_mask(spec)
    mask[0, 3, 5, 5] = np.inf
    return mask


def _left_only_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    mask = np.zeros_like(spec)
    mask[:, 0] = 1.0  # L.re only
    return mask


class NonArraySession(FakeSession):
    def run(
        self, output_names: Sequence[str] | None, input_feed: Feed
    ) -> list[npt.NDArray[np.float32]]:
        return [[0.0]]  # type: ignore[list-item]  # a session returning a non-ndarray


def _model(session: FakeSession) -> MaskModel:
    def factory(path: str, providers: Sequence[str]) -> Session:
        return session

    return MaskModel(Path("fake.onnx"), session_factory=factory)


def _noise(samples: int, seed: int = 0) -> npt.NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    return rng.uniform(-0.5, 0.5, size=(2, samples)).astype(np.float32)


def _noise_chunk() -> npt.NDArray[np.float32]:
    return _noise(CHUNK)


def _sine_chunk() -> npt.NDArray[np.float32]:
    t = np.arange(CHUNK) / SAMPLE_RATE
    wave = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    return np.stack([wave, wave * 0.5])


def test_ones_mask_returns_a_signal_without_dc_content_as_it_was() -> None:
    chunk = _sine_chunk()

    out = _model(FakeSession(_ones_mask))(chunk)

    np.testing.assert_allclose(out[:, EDGE:-EDGE], chunk[:, EDGE:-EDGE], atol=1e-4)


def test_ones_mask_removes_the_dc_bin_of_a_noise_chunk() -> None:
    chunk = _noise_chunk()
    spec = stft(chunk)
    spec[:, 0, :] = 0

    out = _model(FakeSession(_ones_mask))(chunk)

    np.testing.assert_allclose(out, istft(spec, CHUNK), atol=1e-4)


def test_zero_mask_returns_silence() -> None:
    out = _model(FakeSession(_zero_mask))(_noise_chunk())

    assert not np.any(out)


def test_mask_that_keeps_only_the_left_channel_silences_the_right() -> None:
    out = _model(FakeSession(_left_only_mask))(_noise_chunk())

    assert not np.any(out[1])


def test_mask_that_keeps_only_the_left_channel_keeps_the_left() -> None:
    chunk = _sine_chunk()

    out = _model(FakeSession(_left_only_mask))(chunk)

    np.testing.assert_allclose(out[0, EDGE:-EDGE], chunk[0, EDGE:-EDGE], atol=1e-4)


def test_session_gets_the_spectrogram_as_float32_in_the_model_layout() -> None:
    session = FakeSession(_ones_mask)

    _model(session)(_noise_chunk())

    assert (session.feeds[0]["spec"].shape, session.feeds[0]["spec"].dtype) == (
        (1, 4, BINS, FRAMES),
        np.dtype(np.float32),
    )


def test_output_is_float32_with_the_chunk_shape() -> None:
    out = _model(FakeSession(_ones_mask))(_noise_chunk())

    assert (out.shape, out.dtype) == ((2, CHUNK), np.dtype(np.float32))


@pytest.mark.parametrize(
    "shape",
    [[1, 4, BINS, FRAMES], ["batch", 4, BINS, FRAMES], [None, 4, BINS, "frames"]],
    ids=["static", "named-dynamic", "unknown-dynamic"],
)
def test_declared_shapes_that_match_or_are_dynamic_are_accepted(
    shape: list[int | str | None],
) -> None:
    session = FakeSession(_ones_mask, inputs=[FakeNode("spec", shape)])

    assert _model(session) is not None


@pytest.mark.parametrize(
    ("inputs", "outputs"),
    [
        ([FakeNode("x", MODEL_SHAPE)], [FakeNode("mask", MODEL_SHAPE)]),
        ([FakeNode("spec", MODEL_SHAPE)], [FakeNode("y", MODEL_SHAPE)]),
        (
            [FakeNode("spec", MODEL_SHAPE), FakeNode("spec2", MODEL_SHAPE)],
            [FakeNode("mask", MODEL_SHAPE)],
        ),
        ([FakeNode("spec", MODEL_SHAPE)], []),
        (
            [FakeNode("spec", MODEL_SHAPE)],
            [FakeNode("mask", MODEL_SHAPE), FakeNode("extra", MODEL_SHAPE)],
        ),
        ([FakeNode("spec", [1, 2, BINS, FRAMES])], [FakeNode("mask", MODEL_SHAPE)]),
        ([FakeNode("spec", MODEL_SHAPE)], [FakeNode("mask", [1, 4, BINS, FRAMES + 1])]),
        ([FakeNode("spec", [1, 4, BINS])], [FakeNode("mask", MODEL_SHAPE)]),
    ],
    ids=[
        "input-name",
        "output-name",
        "two-inputs",
        "no-outputs",
        "two-outputs",
        "input-shape",
        "output-shape",
        "input-rank",
    ],
)
def test_a_model_with_another_contract_is_rejected(
    inputs: list[FakeNode], outputs: list[FakeNode]
) -> None:
    session = FakeSession(_ones_mask, inputs=inputs, outputs=outputs)

    with pytest.raises(ValueError, match=r"fake\.onnx"):
        _model(session)


def test_a_mask_of_1j_rotates_every_frequency_by_a_quarter_turn() -> None:
    t = np.arange(CHUNK) / SAMPLE_RATE
    cosine = (0.5 * np.cos(2 * np.pi * 1000.0 * t)).astype(np.float32)
    chunk = np.stack([cosine, cosine])
    expected = -0.5 * np.sin(2 * np.pi * 1000.0 * t)

    out = _model(FakeSession(_rotating_mask))(chunk)

    np.testing.assert_allclose(out[0, EDGE:-EDGE], expected[EDGE:-EDGE], atol=1e-3)


@pytest.mark.parametrize("mask_fn", [_nan_mask, _inf_mask], ids=["nan", "inf"])
def test_a_mask_with_non_finite_values_is_rejected(mask_fn: MaskFn) -> None:
    model = _model(FakeSession(mask_fn))

    with pytest.raises(ValueError, match="finite"):
        model(_noise_chunk())


def test_a_non_array_output_is_rejected() -> None:
    model = _model(NonArraySession(_ones_mask))

    with pytest.raises(ValueError, match="ndarray"):
        model(_noise_chunk())


def test_the_path_reaches_the_session_factory_as_a_string() -> None:
    seen: list[tuple[str, Sequence[str]]] = []

    def factory(path: str, providers: Sequence[str]) -> Session:
        seen.append((path, providers))
        return FakeSession(_ones_mask)

    MaskModel(Path("models/sep.onnx"), session_factory=factory)

    assert seen[0][0] == str(Path("models/sep.onnx"))


def test_the_providers_reach_the_session_factory() -> None:
    seen: list[Sequence[str]] = []

    def factory(path: str, providers: Sequence[str]) -> Session:
        seen.append(providers)
        return FakeSession(_ones_mask)

    MaskModel(
        Path("sep.onnx"), ["CUDAExecutionProvider", "CPUExecutionProvider"], session_factory=factory
    )

    assert list(seen[0]) == ["CUDAExecutionProvider", "CPUExecutionProvider"]


def test_the_default_provider_is_the_cpu() -> None:
    seen: list[Sequence[str]] = []

    def factory(path: str, providers: Sequence[str]) -> Session:
        seen.append(providers)
        return FakeSession(_ones_mask)

    MaskModel(Path("sep.onnx"), session_factory=factory)

    assert list(seen[0]) == ["CPUExecutionProvider"]


def test_a_chunk_of_the_wrong_length_is_rejected() -> None:
    model = _model(FakeSession(_ones_mask))

    with pytest.raises(ValueError, match="shape"):
        model(np.zeros((2, CHUNK - 1), dtype=np.float32))


def test_a_mono_chunk_is_rejected() -> None:
    model = _model(FakeSession(_ones_mask))

    with pytest.raises(ValueError, match="shape"):
        model(np.zeros((1, CHUNK), dtype=np.float32))


def test_a_mask_of_the_wrong_shape_is_rejected() -> None:
    def bad_mask(spec: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        return spec[:, :, :10]

    model = _model(FakeSession(bad_mask))

    with pytest.raises(ValueError, match="shape"):
        model(_noise_chunk())


def test_separate_vocals_keeps_the_length_of_audio_shorter_than_a_chunk() -> None:
    audio = _noise(SAMPLE_RATE // 2)

    out = separate_vocals(audio, _model(FakeSession(_ones_mask)))

    assert out.shape == audio.shape


def test_separate_vocals_runs_the_model_once_per_chunk_position() -> None:
    session = FakeSession(_ones_mask)
    audio = _noise(CHUNK + SAMPLE_RATE)

    separate_vocals(audio, _model(session))

    # Border pad makes 2 * border + length samples; step is half a chunk.
    border = CHUNK // 2
    total = CHUNK + SAMPLE_RATE + 2 * border
    assert len(session.feeds) == -(-total // (CHUNK // 2))
