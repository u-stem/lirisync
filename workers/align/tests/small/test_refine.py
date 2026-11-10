"""Small tests for the `refine` method: the per-line steps and the handler, with a fake model."""

import math
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.ctc_align import CtcAlignmentError, TokenSpan
from lirisync_worker.ctc_model import (
    BLANK,
    FRAME_SAMPLES,
    MIN_SAMPLES,
    SAMPLE_RATE,
    frame_count,
)
from lirisync_worker.ctc_tokens import CharVocab
from lirisync_worker.match_text import Reader, Token
from lirisync_worker.protocol import ProtocolError
from lirisync_worker.refine import (
    MAX_WINDOW_MS,
    Cut,
    LineSettings,
    RefinedLine,
    Window,
    cut_window,
    frame_boundary_ms,
    make_refine,
    refine_line,
    span_log_ratio,
)
from lirisync_worker.server import Registry, Session

Audio = npt.NDArray[np.float32]
LogProbs = npt.NDArray[np.float32]

VOCAB = CharVocab({"<pad>": 0, "あ": 1, "い": 2, "う": 3, "え": 4})
VOCAB_SIZE = 5
TOK_A, TOK_I, TOK_U = 1, 2, 3  # token ids of あ い う
HIT = 0.9  # probability of the scripted label in a scripted frame


def _samples(ms: int) -> int:
    return ms * SAMPLE_RATE // 1000


def _audio(ms: int) -> Audio:
    return np.zeros(_samples(ms), dtype=np.float32)


def _scripted(labels: list[int], weak: frozenset[int] = frozenset()) -> LogProbs:
    """Frames that each put HIT on their label and share the rest.

    A frame in `weak` is one where the blank is more likely (0.5) than the label (0.4),
    so a path that spells its label there pays for it.
    """
    miss = (1 - HIT) / (VOCAB_SIZE - 1)
    probs = np.full((len(labels), VOCAB_SIZE), miss)
    probs[np.arange(len(labels)), labels] = HIT
    for frame in weak:
        probs[frame] = (1 - 0.9) / (VOCAB_SIZE - 2)
        probs[frame, BLANK] = 0.5
        probs[frame, labels[frame]] = 0.4
    return np.log(probs).astype(np.float32)


class ScriptedModel:
    """Sings `tokens` (each held for `hold` frames) after `lead` blank frames, then stays blank."""

    def __init__(
        self, tokens: list[int], *, lead: int = 5, hold: int = 3, weak: bool = False
    ) -> None:
        self.vocab = VOCAB
        self._tokens = tokens
        self._lead = lead
        self._hold = hold
        self._weak = weak
        self.heard: list[int] = []

    def log_probs(self, audio: Audio) -> LogProbs:
        self.heard.append(audio.shape[0])
        frames = frame_count(audio.shape[0])
        sung = [t for token in self._tokens for t in [token] * self._hold]
        labels = [BLANK] * self._lead + sung
        if len(labels) > frames:
            raise AssertionError(f"the script needs {len(labels)} frames, the window has {frames}")
        weak = frozenset(range(self._lead, len(labels))) if self._weak else frozenset()
        return _scripted(labels + [BLANK] * (frames - len(labels)), weak)


class UniformModel:
    """Every frame is equally likely to be any token."""

    def __init__(self) -> None:
        self.vocab = VOCAB

    def log_probs(self, audio: Audio) -> LogProbs:
        frames = frame_count(audio.shape[0])
        return np.full((frames, VOCAB_SIZE), math.log(1 / VOCAB_SIZE), dtype=np.float32)


def _number(value: float | None) -> float:
    """`value` as a number; a test that gets None instead fails here."""
    if value is None:
        raise AssertionError("expected a number, got None")
    return value


def _identity(line: str) -> str:
    return line


def _refine(  # noqa: PLR0913 - every argument is a knob of one test scenario
    line: str = "あい",
    window: Window | None = None,
    *,
    model: ScriptedModel | UniformModel | None = None,
    margin_ms: int = 0,
    audio_ms: int = 10_000,
    spell: Callable[[str], str] = _identity,
) -> RefinedLine:
    return refine_line(
        _audio(audio_ms),
        model if model is not None else ScriptedModel([TOK_A, TOK_I]),
        line,
        window if window is not None else Window(1000, 2000),
        LineSettings(margin_ms, spell),
    )


# --- time conversion ---------------------------------------------------------


def test_the_first_frame_boundary_is_two_milliseconds_into_the_window() -> None:
    assert frame_boundary_ms(0, 0) == 2


def test_a_frame_boundary_moves_twenty_milliseconds_per_frame() -> None:
    assert frame_boundary_ms(0, 5) == 102


def test_a_frame_boundary_is_offset_by_the_window_start() -> None:
    assert frame_boundary_ms(1000, 5) == 1102


def test_a_frame_boundary_rounds_down_to_a_whole_millisecond() -> None:
    assert frame_boundary_ms(0, 1) == 22  # 22.5 ms


def test_a_frame_boundary_is_ten_milliseconds_before_the_frame_center() -> None:
    center_ms = (FRAME_SAMPLES * 7 + MIN_SAMPLES // 2) * 1000 // SAMPLE_RATE  # 152.5 -> 152
    assert frame_boundary_ms(0, 7) == center_ms - 10


def test_a_frame_boundary_stays_an_integer() -> None:
    assert isinstance(frame_boundary_ms(1234, 3), int)


# --- cutting the window ------------------------------------------------------


def test_a_window_is_cut_from_its_start_to_its_end() -> None:
    assert cut_window(Window(1000, 2000), 0, _samples(10_000)) == Cut(
        start_ms=1000, start=_samples(1000), stop=_samples(2000)
    )


def test_the_margin_widens_the_window_on_both_sides() -> None:
    assert cut_window(Window(1000, 2000), 300, _samples(10_000)) == Cut(
        start_ms=700, start=_samples(700), stop=_samples(2300)
    )


def test_the_window_start_is_clamped_at_zero() -> None:
    assert cut_window(Window(100, 2000), 300, _samples(10_000)).start_ms == 0


def test_the_clamped_window_starts_at_the_first_sample() -> None:
    assert cut_window(Window(100, 2000), 300, _samples(10_000)).start == 0


def test_the_window_end_is_clamped_at_the_audio_length() -> None:
    assert cut_window(Window(9000, 9900), 300, _samples(10_000)).stop == _samples(10_000)


def test_a_window_past_the_end_of_the_audio_is_empty() -> None:
    assert cut_window(Window(11_000, 12_000), 0, _samples(10_000)).samples == 0


def test_a_window_cut_length_is_its_sample_count() -> None:
    assert cut_window(Window(1000, 2000), 0, _samples(10_000)).samples == _samples(1000)


# --- the log ratio -----------------------------------------------------------


def _hand_made() -> LogProbs:
    """Six frames over blank, あ, い; the line is sung in frames 1 to 3."""
    probs = np.array(
        [
            [0.90, 0.05, 0.05],  # before the line: blank, as forced
            [0.10, 0.80, 0.10],  # あ, the best token
            [0.60, 0.30, 0.10],  # あ, but blank is more likely: costs log(0.3 / 0.6)
            [0.05, 0.05, 0.90],  # い, the best token
            [0.20, 0.40, 0.40],  # after the line: blank is forced but not the best
            [0.30, 0.30, 0.40],  # after the line
        ]
    )
    return np.log(probs).astype(np.float32)


def test_the_log_ratio_is_the_shortfall_per_frame_over_the_sung_frames() -> None:
    ratio = span_log_ratio(_hand_made(), [1, 2], [TokenSpan(1, 3), TokenSpan(3, 4)], BLANK)

    assert ratio == pytest.approx(math.log(0.3 / 0.6) / 3)


def test_the_log_ratio_ignores_the_frames_outside_the_line() -> None:
    spans = [TokenSpan(1, 3), TokenSpan(3, 4)]
    noisy = _hand_made()
    noisy[0] = np.log(np.array([0.01, 0.50, 0.49]))
    noisy[4:] = np.log(np.array([0.01, 0.50, 0.49]))

    assert span_log_ratio(noisy, [1, 2], spans, BLANK) == span_log_ratio(
        _hand_made(), [1, 2], spans, BLANK
    )


def test_the_log_ratio_counts_the_blank_frames_between_tokens() -> None:
    probs = np.log(
        np.array(
            [
                [0.10, 0.80, 0.10],  # あ
                [0.50, 0.25, 0.25],  # blank between the tokens: best, no cost
                [0.10, 0.10, 0.80],  # い
            ]
        )
    ).astype(np.float32)

    assert span_log_ratio(probs, [1, 2], [TokenSpan(0, 1), TokenSpan(2, 3)], BLANK) == (
        pytest.approx(0.0, abs=1e-6)
    )


def test_the_log_ratio_is_never_positive() -> None:
    probs = np.log(np.array([[0.2, 0.8, 0.0 + 1e-12]])).astype(np.float32)

    assert span_log_ratio(probs, [1], [TokenSpan(0, 1)], BLANK) <= 0.0


# --- one line ----------------------------------------------------------------


def test_a_line_without_a_window_has_no_window() -> None:
    result = refine_line(_audio(5000), UniformModel(), "あい", None, LineSettings(0, _identity))

    assert result.status == "no_window"


def test_a_line_without_a_window_reports_no_times() -> None:
    result = refine_line(_audio(5000), UniformModel(), "あい", None, LineSettings(0, _identity))

    assert (result.start_ms, result.end_ms, result.log_ratio) == (None, None, None)


def test_a_line_without_a_window_is_not_spelled() -> None:
    spelled: list[str] = []

    def spy(line: str) -> str:
        spelled.append(line)
        return line

    refine_line(_audio(5000), UniformModel(), "あい", None, LineSettings(0, spy))

    assert spelled == []


def test_a_line_that_is_found_is_refined() -> None:
    assert _refine().status == "refined"


def test_the_line_starts_at_the_first_frame_it_is_sung_in() -> None:
    # Five blank frames, then あ: the first span starts at frame 5.
    assert _refine(window=Window(1000, 2000)).start_ms == frame_boundary_ms(1000, 5)


def test_the_line_ends_at_the_end_of_the_last_frame_it_is_sung_in() -> None:
    # あ in frames 5-7 and い in frames 8-10: the last span ends at frame 11.
    assert _refine(window=Window(1000, 2000)).end_ms == frame_boundary_ms(1000, 11)


def test_the_times_are_relative_to_the_start_of_the_margin() -> None:
    assert _refine(window=Window(1000, 2000), margin_ms=100).start_ms == frame_boundary_ms(900, 5)


def test_the_times_follow_a_window_clamped_at_the_start_of_the_audio() -> None:
    assert _refine(window=Window(40, 2000), margin_ms=100).start_ms == frame_boundary_ms(0, 5)


def test_the_times_are_integers() -> None:
    assert isinstance(_refine().start_ms, int)


def test_the_model_hears_the_window_with_its_margin() -> None:
    model = ScriptedModel([TOK_A, TOK_I])
    _refine(window=Window(1000, 2000), margin_ms=250, model=model)

    assert model.heard == [_samples(1500)]


def test_the_model_hears_only_to_the_end_of_the_audio() -> None:
    model = ScriptedModel([TOK_A, TOK_I])
    _refine(window=Window(9000, 9900), margin_ms=500, model=model, audio_ms=10_000)

    assert model.heard == [_samples(1500)]


def test_a_perfectly_supported_line_has_a_log_ratio_of_zero() -> None:
    assert _refine().log_ratio == pytest.approx(0.0, abs=1e-6)


def test_a_line_the_audio_does_not_support_has_a_negative_log_ratio() -> None:
    # The model sings う where the line says あい, so the forced path loses at every character.
    result = _refine("あい", model=ScriptedModel([TOK_U, TOK_U]))

    assert _number(result.log_ratio) < -1.0


def _weak_ratio(lead: int, window: Window) -> float | None:
    return _refine(
        model=ScriptedModel([TOK_A, TOK_I], lead=lead, weak=True), window=window
    ).log_ratio


def test_a_weakly_sung_line_has_a_negative_log_ratio() -> None:
    assert _number(_weak_ratio(2, Window(1000, 1400))) < -0.05


def test_blank_frames_around_the_line_do_not_change_the_log_ratio() -> None:
    # The second window has 18 more blank frames before the line and 80 more after it.
    assert _weak_ratio(2, Window(1000, 1400)) == pytest.approx(_weak_ratio(20, Window(1000, 3000)))


def test_a_line_with_no_forceable_character_has_no_text() -> None:
    assert _refine(spell=lambda _line: "").status == "no_text"


def test_a_line_whose_characters_are_all_outside_the_vocabulary_has_no_text() -> None:
    assert _refine(spell=lambda _line: "xyz").status == "no_text"


def test_a_line_with_no_text_reports_no_times() -> None:
    result = _refine(spell=lambda _line: "")

    assert (result.start_ms, result.end_ms, result.log_ratio) == (None, None, None)


def test_skipped_characters_are_counted() -> None:
    assert _refine(spell=lambda _line: "あxい").skipped_chars == 1


def test_skipped_characters_are_counted_when_nothing_is_left() -> None:
    assert _refine(spell=lambda _line: "xyz").skipped_chars == 3


def test_a_line_with_nothing_skipped_counts_zero() -> None:
    assert _refine().skipped_chars == 0


def test_a_window_over_the_limit_is_too_long() -> None:
    result = _refine(window=Window(0, MAX_WINDOW_MS + 1), model=UniformModel(), audio_ms=60_000)

    assert result.status == "too_long"


def test_a_window_at_the_limit_is_not_too_long() -> None:
    result = _refine(window=Window(0, MAX_WINDOW_MS), model=UniformModel(), audio_ms=60_000)

    assert result.status == "refined"


def test_the_margin_counts_toward_the_limit() -> None:
    result = _refine(
        window=Window(1000, 1000 + MAX_WINDOW_MS - 100),
        margin_ms=100,
        model=UniformModel(),
        audio_ms=60_000,
    )

    assert result.status == "too_long"


def test_the_part_of_the_window_beyond_the_audio_does_not_count_toward_the_limit() -> None:
    result = _refine(
        window=Window(0, 10_000), margin_ms=MAX_WINDOW_MS, model=UniformModel(), audio_ms=20_000
    )

    assert result.status == "refined"


def test_a_too_long_line_still_counts_its_skipped_characters() -> None:
    result = _refine(
        window=Window(0, MAX_WINDOW_MS + 1),
        model=UniformModel(),
        audio_ms=60_000,
        spell=lambda _line: "あx",
    )

    assert result.skipped_chars == 1


def test_a_window_shorter_than_one_model_frame_is_too_short() -> None:
    # 20 ms is 320 samples, short of the 400 the model needs.
    assert _refine(window=Window(1000, 1020), model=UniformModel()).status == "too_short"


def test_a_window_of_exactly_one_model_frame_is_enough_for_one_character() -> None:
    # 25 ms is 400 samples: one frame.
    result = _refine("あ", window=Window(1000, 1025), model=UniformModel())

    assert result.status == "refined"


def test_a_window_past_the_end_of_the_audio_is_too_short() -> None:
    assert _refine(window=Window(20_000, 21_000), model=UniformModel()).status == "too_short"


def test_a_window_with_fewer_frames_than_characters_is_too_short() -> None:
    # 25 ms is one frame; two characters need two.
    assert _refine("あい", window=Window(1000, 1025), model=UniformModel()).status == "too_short"


def test_a_window_with_no_room_for_the_blank_between_equal_characters_is_too_short() -> None:
    # 45 ms is two frames; ああ needs three (a blank sits between the two).
    assert _refine("ああ", window=Window(1000, 1045), model=UniformModel()).status == "too_short"


class NarrowModel(UniformModel):
    """Returns fewer columns than the vocabulary has ids: a model and vocab that do not match."""

    def log_probs(self, audio: Audio) -> LogProbs:
        return super().log_probs(audio)[:, :1]


def test_a_model_that_does_not_match_its_vocabulary_is_an_error_not_too_short() -> None:
    with pytest.raises(CtcAlignmentError):
        _refine(model=NarrowModel())


def test_a_too_short_line_reports_no_times() -> None:
    result = _refine(window=Window(1000, 1020), model=UniformModel())

    assert (result.start_ms, result.end_ms, result.log_ratio) == (None, None, None)


def test_a_too_short_line_still_counts_its_skipped_characters() -> None:
    result = _refine(window=Window(1000, 1020), model=UniformModel(), spell=lambda _line: "あxx")

    assert result.skipped_chars == 2


def test_a_window_the_model_never_has_to_hear_is_not_sent_to_it() -> None:
    model = ScriptedModel([TOK_A, TOK_I])
    _refine(window=Window(1000, 1020), model=model)

    assert model.heard == []


# --- the handler -------------------------------------------------------------


def _char_reader(text: str) -> Iterable[Token]:
    return [Token(surface=ch, reading=ch) for ch in text]


class _Run:
    """One handler over a model directory in `tmp_path`, with fake decoder and model."""

    def __init__(self, tmp_path: Path, *, audio_ms: int = 10_000) -> None:
        self.audio_ms = audio_ms
        self.decoded: list[Path] = []
        self.loaded: list[Path] = []
        self.readers_made = 0
        self.progress: list[tuple[str, float, int | None]] = []
        self.model_dir = tmp_path / "aligner"
        self.model_dir.mkdir()
        (self.model_dir / "model.int8.onnx").write_bytes(b"x")
        (self.model_dir / "vocab.json").write_text("{}")
        self.audio = tmp_path / "vocals.wav"
        self.session = Session(registry=Registry())
        self.session.progress_sink = lambda stage, ratio, eta: self.progress.append(
            (stage, ratio, eta)
        )
        self.handler = make_refine(self.reader, decoder=self.decode, model_loader=self.load)

    def reader(self) -> Reader:
        self.readers_made += 1
        return _char_reader

    def decode(self, path: Path) -> Audio:
        self.decoded.append(path)
        return _audio(self.audio_ms)

    def load(self, path: Path) -> ScriptedModel:
        self.loaded.append(path)
        return ScriptedModel([TOK_A, TOK_I])

    def params(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "audio": str(self.audio),
            "model": str(self.model_dir),
            "lyrics": ["あい", "あい", "あい"],
            "windows": [{"startMs": 1000, "endMs": 2000}, None, {"startMs": 3000, "endMs": 3010}],
            "spelling": "surface",
            "ignored": [],
            "marginMs": 0,
        }
        return base | overrides

    def call(self, **overrides: object) -> dict[str, object]:
        return self.handler(self.session, self.params(**overrides))


def _lines(result: Mapping[str, object]) -> list[dict[str, object]]:
    lines = result["lines"]
    assert isinstance(lines, list)
    return lines


def _code(run: _Run, **overrides: object) -> str:
    with pytest.raises(ProtocolError) as error:
        run.call(**overrides)
    return error.value.code


def test_the_result_has_one_line_per_lyric(tmp_path: Path) -> None:
    assert len(_lines(_Run(tmp_path).call())) == 3


def test_the_statuses_follow_the_windows(tmp_path: Path) -> None:
    lines = _lines(_Run(tmp_path).call())

    assert [line["status"] for line in lines] == ["refined", "no_window", "too_short"]


def test_a_refined_line_is_reported_in_wire_form(tmp_path: Path) -> None:
    line = _lines(_Run(tmp_path).call())[0]

    assert line == {
        "status": "refined",
        "startMs": frame_boundary_ms(1000, 5),
        "endMs": frame_boundary_ms(1000, 11),
        "logRatio": pytest.approx(0.0, abs=1e-6),
        "skippedChars": 0,
    }


def test_a_line_without_a_window_is_reported_in_wire_form(tmp_path: Path) -> None:
    line = _lines(_Run(tmp_path).call())[1]

    assert line == {
        "status": "no_window",
        "startMs": None,
        "endMs": None,
        "logRatio": None,
        "skippedChars": 0,
    }


def test_the_audio_is_decoded_from_the_given_path(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.decoded == [run.audio.resolve()]


def test_the_model_is_loaded_from_the_given_directory(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert run.loaded == [run.model_dir.resolve()]


def test_the_same_model_is_loaded_once_for_two_requests(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()
    run.call()

    assert len(run.loaded) == 1


def test_a_changed_model_file_is_loaded_again(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()
    (run.model_dir / "model.int8.onnx").write_bytes(b"a different model")
    run.call()

    assert len(run.loaded) == 2


def test_another_model_directory_is_loaded_again(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()
    other = tmp_path / "other"
    other.mkdir()
    (other / "model.int8.onnx").write_bytes(b"x")
    (other / "vocab.json").write_text("{}")
    run.call(model=str(other))

    assert len(run.loaded) == 2


def test_progress_is_reported_per_line_under_the_refine_stage(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()

    assert [(stage, ratio) for stage, ratio, _ in run.progress] == [
        ("refine", 0.0),
        ("refine", pytest.approx(1 / 3)),
        ("refine", pytest.approx(2 / 3)),
        ("refine", 1.0),
    ]


def test_the_reader_is_not_made_for_the_surface_spelling(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call(spelling="surface")

    assert run.readers_made == 0


def test_the_reader_is_made_once_for_the_kana_spelling(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call(spelling="kana")
    run.call(spelling="kana")

    assert run.readers_made == 1


def test_the_reader_is_not_made_when_no_line_has_a_window(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call(spelling="kana", windows=[None, None, None])

    assert run.readers_made == 0


def test_the_kana_spelling_is_forced_in_the_reading(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    result = run.call(spelling="kana", lyrics=["ア", "", ""])

    assert _lines(result)[0]["skippedChars"] == 0


def test_the_surface_spelling_keeps_the_katakana_the_vocabulary_lacks(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    result = run.call(spelling="surface", lyrics=["ア", "", ""])

    assert _lines(result)[0]["skippedChars"] == 1


def test_ignored_characters_are_not_forced(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    result = run.call(lyrics=["あ♪い", "", ""], ignored=["♪"])

    assert _lines(result)[0]["skippedChars"] == 0


def test_a_character_the_vocabulary_lacks_is_counted_as_skipped(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    result = run.call(lyrics=["あzい", "", ""])

    assert _lines(result)[0]["skippedChars"] == 1


def test_a_model_directory_without_the_model_file_is_model_missing(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    (run.model_dir / "model.int8.onnx").unlink()

    assert _code(run) == "model_missing"


def test_a_model_directory_without_the_vocabulary_is_model_missing(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    (run.model_dir / "vocab.json").unlink()

    assert _code(run) == "model_missing"


def test_repeated_requests_load_the_model_once(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()
    run.call()

    assert len(run.loaded) == 1


def test_a_replaced_vocabulary_loads_the_model_again(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    run.call()
    (run.model_dir / "vocab.json").write_text('{"<unk>": 0}')
    run.call()

    assert len(run.loaded) == 2


def test_a_missing_model_directory_is_model_missing(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    assert _code(run, model=str(tmp_path / "gone")) == "model_missing"


def test_a_model_that_fails_to_load_is_model_missing(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    def broken(_path: Path) -> ScriptedModel:
        raise ValueError("vocab is not valid JSON")

    run.handler = make_refine(run.reader, decoder=run.decode, model_loader=broken)

    assert _code(run) == "model_missing"


def test_a_failed_model_load_is_not_remembered(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    attempts: list[Path] = []

    def flaky(path: Path) -> ScriptedModel:
        attempts.append(path)
        if len(attempts) == 1:
            raise ValueError("first attempt fails")
        return ScriptedModel([TOK_A, TOK_I])

    run.handler = make_refine(run.reader, decoder=run.decode, model_loader=flaky)
    with pytest.raises(ProtocolError):
        run.call()
    run.call()

    assert len(attempts) == 2


def test_an_inference_runtime_that_cannot_be_imported_is_internal(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    def missing_runtime(_path: Path) -> ScriptedModel:
        raise ImportError("No module named onnxruntime")

    run.handler = make_refine(run.reader, decoder=run.decode, model_loader=missing_runtime)

    assert _code(run) == "internal"


def test_audio_with_no_samples_is_audio_unreadable(tmp_path: Path) -> None:
    run = _Run(tmp_path, audio_ms=0)

    assert _code(run) == "audio_unreadable"


def test_an_input_that_is_a_directory_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)

    assert _code(run, audio=str(tmp_path)) == "invalid_request"


# --- params that do not match the schema -------------------------------------


def test_windows_of_another_length_than_lyrics_are_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), windows=[None]) == "invalid_request"


def test_a_window_ending_before_it_starts_is_an_invalid_request(tmp_path: Path) -> None:
    windows = [{"startMs": 2000, "endMs": 1000}, None, None]

    assert _code(_Run(tmp_path), windows=windows) == "invalid_request"


def test_a_negative_window_start_is_an_invalid_request(tmp_path: Path) -> None:
    windows = [{"startMs": -1, "endMs": 1000}, None, None]

    assert _code(_Run(tmp_path), windows=windows) == "invalid_request"


def test_a_fractional_window_end_is_an_invalid_request(tmp_path: Path) -> None:
    windows = [{"startMs": 0, "endMs": 1000.5}, None, None]

    assert _code(_Run(tmp_path), windows=windows) == "invalid_request"


def test_a_window_with_an_extra_key_is_an_invalid_request(tmp_path: Path) -> None:
    windows = [{"startMs": 0, "endMs": 1000, "x": 1}, None, None]

    assert _code(_Run(tmp_path), windows=windows) == "invalid_request"


def test_an_unknown_spelling_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), spelling="romaji") == "invalid_request"


def test_a_negative_margin_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), marginMs=-1) == "invalid_request"


def test_a_fractional_margin_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), marginMs=0.5) == "invalid_request"


def test_a_missing_margin_is_an_invalid_request(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    params = run.params()
    del params["marginMs"]

    with pytest.raises(ProtocolError) as error:
        run.handler(run.session, params)

    assert error.value.code == "invalid_request"


def test_an_extra_param_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), extra=1) == "invalid_request"


def test_a_repeated_ignored_character_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), ignored=["a", "a"]) == "invalid_request"


def test_an_ignored_item_of_two_characters_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), ignored=["ab"]) == "invalid_request"


def test_an_empty_audio_path_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), audio="") == "invalid_request"


def test_an_empty_model_path_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), model="") == "invalid_request"


def test_a_numeric_lyric_is_an_invalid_request(tmp_path: Path) -> None:
    assert _code(_Run(tmp_path), lyrics=[1, "あ", "あ"]) == "invalid_request"


def test_a_bad_request_decodes_nothing(tmp_path: Path) -> None:
    run = _Run(tmp_path)
    with pytest.raises(ProtocolError):
        run.call(spelling="romaji")

    assert run.decoded == []
