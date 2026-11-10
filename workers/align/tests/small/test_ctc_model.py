import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.ctc_model import (
    BLANK,
    FRAME_MS,
    FRAME_SAMPLES,
    SAMPLE_RATE,
    CharCtcModel,
    Session,
    frame_count,
)

VOCAB = {"<unk>": 0, "あ": 1, "い": 2, "▁あ": 3}
LOGIT_COLUMNS = 6  # the vocabulary's ids plus special tokens, as in the real model
Feed = dict[str, npt.NDArray[np.float32]]
LogitsFn = Callable[[npt.NDArray[np.float32]], object]


@dataclass(frozen=True)
class FakeNode:
    name: str
    shape: Sequence[int | str | None]


def _zero_logits(values: npt.NDArray[np.float32]) -> object:
    return np.zeros((values.shape[0], frame_count(values.shape[1]), LOGIT_COLUMNS), np.float32)


@dataclass
class FakeSession:
    """Stands in for an onnxruntime session; `logits_fn` maps `input_values` to the output."""

    logits_fn: LogitsFn = _zero_logits
    inputs: list[FakeNode] = field(
        default_factory=lambda: [FakeNode("input_values", ["batch", "samples"])]
    )
    outputs: list[FakeNode] = field(
        default_factory=lambda: [FakeNode("logits", ["batch", "frames", LOGIT_COLUMNS])]
    )
    feeds: list[Feed] = field(default_factory=list)

    def get_inputs(self) -> Sequence[FakeNode]:
        return self.inputs

    def get_outputs(self) -> Sequence[FakeNode]:
        return self.outputs

    def run(self, output_names: Sequence[str] | None, input_feed: Feed) -> list[object]:
        self.feeds.append(input_feed)
        return [self.logits_fn(input_feed["input_values"])]


def _write_model_dir(directory: Path, vocab: object = VOCAB) -> Path:
    (directory / "vocab.json").write_text(json.dumps(vocab), encoding="utf-8")
    (directory / "model.int8.onnx").write_bytes(b"")
    return directory


def _model(directory: Path, session: FakeSession | None = None) -> CharCtcModel:
    chosen = session or FakeSession()
    return CharCtcModel(directory, session_factory=lambda _path, _providers: _as_session(chosen))


def _as_session(session: FakeSession) -> Session:
    return session


def _audio(samples: int = 4000, seed: int = 0) -> npt.NDArray[np.float32]:
    return np.random.default_rng(seed).normal(0.0, 0.1, samples).astype(np.float32)


# constants


def test_the_sample_rate_is_16_khz() -> None:
    assert SAMPLE_RATE == 16000


def test_a_frame_is_320_samples() -> None:
    assert FRAME_SAMPLES == 320


def test_a_frame_lasts_20_ms() -> None:
    assert FRAME_MS * SAMPLE_RATE == FRAME_SAMPLES * 1000


def test_blank_is_id_zero() -> None:
    assert BLANK == 0


# construction


def test_the_session_is_opened_on_the_model_file(tmp_path: Path) -> None:
    opened: list[str] = []

    def factory(path: str, providers: Sequence[str]) -> Session:
        opened.append(path)
        return _as_session(FakeSession())

    CharCtcModel(_write_model_dir(tmp_path), session_factory=factory)

    assert opened == [str(tmp_path / "model.int8.onnx")]


def test_the_session_is_opened_with_the_given_providers(tmp_path: Path) -> None:
    seen: list[Sequence[str]] = []

    def factory(path: str, providers: Sequence[str]) -> Session:
        seen.append(providers)
        return _as_session(FakeSession())

    CharCtcModel(_write_model_dir(tmp_path), ("DmlExecutionProvider",), session_factory=factory)

    assert seen == [("DmlExecutionProvider",)]


def test_the_vocabulary_exposes_its_one_character_tokens(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    assert model.vocab.encode("あい").ids == (1, 2)


def test_an_input_with_another_name_is_rejected(tmp_path: Path) -> None:
    session = FakeSession(inputs=[FakeNode("audio", ["batch", "samples"])])

    with pytest.raises(ValueError, match="input_values"):
        _model(_write_model_dir(tmp_path), session)


def test_a_second_input_is_rejected(tmp_path: Path) -> None:
    session = FakeSession(
        inputs=[FakeNode("input_values", ["batch", "samples"]), FakeNode("mask", ["batch"])]
    )

    with pytest.raises(ValueError, match="input_values"):
        _model(_write_model_dir(tmp_path), session)


def test_an_output_with_another_name_is_rejected(tmp_path: Path) -> None:
    session = FakeSession(outputs=[FakeNode("hidden", ["batch", "frames", LOGIT_COLUMNS])])

    with pytest.raises(ValueError, match="logits"):
        _model(_write_model_dir(tmp_path), session)


def test_a_second_output_is_rejected(tmp_path: Path) -> None:
    session = FakeSession(
        outputs=[
            FakeNode("logits", ["batch", "frames", LOGIT_COLUMNS]),
            FakeNode("extra", ["batch"]),
        ]
    )

    with pytest.raises(ValueError, match="logits"):
        _model(_write_model_dir(tmp_path), session)


def test_logits_with_too_few_columns_for_the_vocabulary_are_rejected(tmp_path: Path) -> None:
    session = FakeSession(outputs=[FakeNode("logits", ["batch", "frames", 3])])

    with pytest.raises(ValueError, match="columns"):
        _model(_write_model_dir(tmp_path), session)


def test_logits_with_exactly_the_vocabulary_size_are_accepted(tmp_path: Path) -> None:
    session = FakeSession(outputs=[FakeNode("logits", ["batch", "frames", 4])])

    assert _model(_write_model_dir(tmp_path), session).vocab.encode("あ").ids == (1,)


def test_logits_with_a_dynamic_last_dimension_are_accepted(tmp_path: Path) -> None:
    session = FakeSession(outputs=[FakeNode("logits", ["batch", "frames", "classes"])])

    assert _model(_write_model_dir(tmp_path), session) is not None


def test_logits_that_are_not_three_dimensional_are_rejected(tmp_path: Path) -> None:
    session = FakeSession(outputs=[FakeNode("logits", ["frames", LOGIT_COLUMNS])])

    with pytest.raises(ValueError, match="logits"):
        _model(_write_model_dir(tmp_path), session)


def test_an_input_that_is_not_two_dimensional_is_rejected(tmp_path: Path) -> None:
    session = FakeSession(inputs=[FakeNode("input_values", ["samples"])])

    with pytest.raises(ValueError, match="input_values"):
        _model(_write_model_dir(tmp_path), session)


# vocabulary file


@pytest.mark.parametrize(
    "vocab",
    [
        pytest.param(["<unk>", "あ"], id="list"),
        pytest.param({"<unk>": 0, "あ": "1"}, id="string-id"),
        pytest.param({"<unk>": 0, "あ": 1.0}, id="float-id"),
        pytest.param({"<unk>": 0, "あ": True}, id="bool-id"),
    ],
)
def test_a_vocabulary_that_is_not_a_map_of_integer_ids_is_rejected(
    tmp_path: Path, vocab: object
) -> None:
    with pytest.raises(ValueError, match="vocab"):
        _model(_write_model_dir(tmp_path, vocab))


def test_a_duplicate_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _model(_write_model_dir(tmp_path, {"<unk>": 0, "あ": 1, "い": 1}))


def test_a_negative_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="negative"):
        _model(_write_model_dir(tmp_path, {"<unk>": 0, "あ": -1}))


def test_a_vocabulary_without_the_blank_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="blank"):
        _model(_write_model_dir(tmp_path, {"あ": 1, "い": 2}))


def test_a_vocabulary_file_that_is_not_json_is_rejected(tmp_path: Path) -> None:
    directory = _write_model_dir(tmp_path)
    (directory / "vocab.json").write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="vocab"):
        _model(directory)


# log_probs


def test_log_probs_has_a_row_per_frame(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    assert model.log_probs(_audio(4000)).shape == (12, LOGIT_COLUMNS)


def test_a_frame_needs_400_samples_so_the_count_trails_samples_over_320(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    assert model.log_probs(_audio(32000)).shape == (99, LOGIT_COLUMNS)


# frame_count


@pytest.mark.parametrize(
    ("samples", "frames"),
    [(400, 1), (719, 1), (720, 2), (4000, 12), (32000, 99), (32399, 100), (32400, 101)],
)
def test_frame_count_matches_the_models_convolution_stack(samples: int, frames: int) -> None:
    assert frame_count(samples) == frames


def test_log_probs_is_float32(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    assert model.log_probs(_audio()).dtype == np.float32


def test_log_probs_rows_are_normalized_in_probability(tmp_path: Path) -> None:
    logits = np.random.default_rng(1).normal(0.0, 3.0, (1, 12, LOGIT_COLUMNS)).astype(np.float32)
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: logits))

    sums = np.exp(model.log_probs(_audio(4000))).sum(axis=1)

    assert np.allclose(sums, 1.0, atol=1e-5)


def test_log_probs_is_the_log_softmax_of_the_logits(tmp_path: Path) -> None:
    logits = np.array([[[0.0, 1.0, 2.0, 3.0, 4.0, 5.0]] * 12], np.float32)
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: logits))

    row = model.log_probs(_audio(4000))[0]

    assert row[5] == pytest.approx(5.0 - np.log(np.exp(np.arange(6.0)).sum()), abs=1e-5)


def test_log_probs_stays_finite_for_large_logits(tmp_path: Path) -> None:
    logits = np.full((1, 12, LOGIT_COLUMNS), 1.0e4, np.float32)
    logits[0, :, 2] = 1.0e4 + 5.0
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: logits))

    assert np.isfinite(model.log_probs(_audio(4000))).all()


def test_log_probs_does_not_overflow_for_very_negative_logits(tmp_path: Path) -> None:
    logits = np.full((1, 12, LOGIT_COLUMNS), -1.0e4, np.float32)
    logits[0, :, 4] = -1.0e4 + 1.0
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: logits))

    assert model.log_probs(_audio(4000))[0, 4] == pytest.approx(-np.log1p(5 * np.exp(-1.0)), 1e-4)


def test_the_model_is_fed_one_batch_of_the_whole_clip(tmp_path: Path) -> None:
    session = FakeSession()
    _model(_write_model_dir(tmp_path), session).log_probs(_audio(4000))

    assert session.feeds[0]["input_values"].shape == (1, 4000)


def test_the_model_is_fed_float32(tmp_path: Path) -> None:
    session = FakeSession()
    _model(_write_model_dir(tmp_path), session).log_probs(_audio())

    assert session.feeds[0]["input_values"].dtype == np.float32


def test_the_input_is_normalized_like_the_wav2vec2_feature_extractor(tmp_path: Path) -> None:
    audio = _audio(4000, seed=3) * 0.5 + 0.2
    session = FakeSession()
    _model(_write_model_dir(tmp_path), session).log_probs(audio)

    wide = audio.astype(np.float64)
    expected = (wide - wide.mean()) / np.sqrt(wide.var() + 1e-7)

    assert np.allclose(session.feeds[0]["input_values"][0], expected, atol=1e-5)


def test_a_silent_clip_is_fed_as_zeros_not_nan(tmp_path: Path) -> None:
    session = FakeSession()
    _model(_write_model_dir(tmp_path), session).log_probs(np.zeros(4000, np.float32))

    assert not session.feeds[0]["input_values"].any()


def test_log_probs_leaves_the_callers_audio_alone(tmp_path: Path) -> None:
    audio = _audio()
    before = audio.copy()
    _model(_write_model_dir(tmp_path)).log_probs(audio)

    assert np.array_equal(audio, before)


def test_the_shortest_clip_is_400_samples(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    assert model.log_probs(_audio(400)).shape == (1, LOGIT_COLUMNS)


def test_a_clip_below_400_samples_is_rejected(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    with pytest.raises(ValueError, match="400"):
        model.log_probs(_audio(399))


def test_a_two_dimensional_clip_is_rejected(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    with pytest.raises(ValueError, match="1-D"):
        model.log_probs(np.zeros((2, 4000), np.float32))


def test_a_float64_clip_is_rejected(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path))

    with pytest.raises(ValueError, match="float32"):
        model.log_probs(np.zeros(4000, np.float64))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_a_clip_with_a_non_finite_sample_is_rejected(tmp_path: Path, bad: float) -> None:
    audio = _audio()
    audio[10] = bad
    model = _model(_write_model_dir(tmp_path))

    with pytest.raises(ValueError, match="non-finite"):
        model.log_probs(audio)


def test_non_finite_logits_are_rejected(tmp_path: Path) -> None:
    logits = np.zeros((1, 12, LOGIT_COLUMNS), np.float32)
    logits[0, 3, 2] = np.nan
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: logits))

    with pytest.raises(ValueError, match="non-finite"):
        model.log_probs(_audio(4000))


def test_an_output_that_is_not_an_array_is_rejected(tmp_path: Path) -> None:
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: [[0.0]]))

    with pytest.raises(ValueError, match="ndarray"):
        model.log_probs(_audio())


def test_an_output_with_the_wrong_rank_is_rejected(tmp_path: Path) -> None:
    flat = np.zeros((12, LOGIT_COLUMNS), np.float32)
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: flat))

    with pytest.raises(ValueError, match="shape"):
        model.log_probs(_audio(4000))


def test_an_output_with_too_few_columns_is_rejected(tmp_path: Path) -> None:
    narrow = np.zeros((1, 12, 2), np.float32)
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: narrow))

    with pytest.raises(ValueError, match="columns"):
        model.log_probs(_audio(4000))


def test_an_output_with_another_frame_count_is_rejected(tmp_path: Path) -> None:
    short = np.zeros((1, 11, LOGIT_COLUMNS), np.float32)
    model = _model(_write_model_dir(tmp_path), FakeSession(logits_fn=lambda _: short))

    with pytest.raises(ValueError, match="frames"):
        model.log_probs(_audio(4000))
