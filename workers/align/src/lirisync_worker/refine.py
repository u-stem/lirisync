"""The `refine` method: second-stage forced alignment of lyric lines inside their windows.

For each line the first stage found a window; the audio of that window, widened
by a margin, is given to the character CTC model, the line's characters are
forced onto the frames (`ctc_align`), and the first and last frames they occupy
become the line's start and end.

The per-line work (`refine_line`) does not know the protocol. `make_refine`
adds the parsing, the file handling, the model cache and the progress.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self

import numpy as np
import numpy.typing as npt
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from lirisync_worker.audio_io import decode_audio
from lirisync_worker.ctc_align import CtcAlignmentError, TokenSpan, align_ctc
from lirisync_worker.ctc_model import (
    BLANK,
    FRAME_SAMPLES,
    MIN_SAMPLES,
    MODEL_FILE,
    SAMPLE_RATE,
    CharCtcModel,
)
from lirisync_worker.ctc_tokens import CharVocab, kana_text, surface_text
from lirisync_worker.match_text import Reader
from lirisync_worker.protocol import ProtocolError, describe_validation_error
from lirisync_worker.request_files import (
    LatestModel,
    check_input_file,
    model_file_state,
    resolve_path,
)

if TYPE_CHECKING:
    from lirisync_worker.server import Session

STAGE = "refine"
MS_PER_SECOND = 1000
# The longest cut handed to the model. The alignment keeps a table of one byte
# per frame and state, so the window bounds the memory of a single line.
MAX_WINDOW_MS = 30000

# Frame k of the model looks at samples [FRAME_SAMPLES * k, FRAME_SAMPLES * k + MIN_SAMPLES),
# so its center is at FRAME_SAMPLES * k + MIN_SAMPLES // 2 = FRAME_SAMPLES * k + 200. The
# boundary that stands for the frame is 10 ms (160 samples) before that center, which is
# FRAME_SAMPLES * k + 40, the value this expression gives.
_BOUNDARY_OFFSET_SAMPLES = (MIN_SAMPLES - FRAME_SAMPLES) // 2

type Audio = npt.NDArray[np.float32]
type LogProbs = npt.NDArray[np.float32]
type Status = Literal["refined", "no_window", "no_text", "too_long", "too_short"]
type Decoder = Callable[[Path], Audio]
type ModelLoader = Callable[[Path], "Aligner"]

type _Path = Annotated[StrictStr, StringConstraints(min_length=1)]
type _Milliseconds = Annotated[StrictInt, Field(ge=0)]


class Aligner(Protocol):
    """The part of `CharCtcModel` that is used."""

    @property
    def vocab(self) -> CharVocab: ...

    def log_probs(self, audio: Audio) -> LogProbs: ...


@dataclass(frozen=True)
class Window:
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Cut:
    """Where a window, with its margin, lies in the decoded audio."""

    start_ms: int  # the window's start with the margin taken off, not before 0
    start: int  # first sample
    stop: int  # one past the last sample, not past the end of the audio

    @property
    def samples(self) -> int:
        return max(0, self.stop - self.start)


@dataclass(frozen=True)
class RefinedLine:
    status: Status
    start_ms: int | None = None
    end_ms: int | None = None
    log_ratio: float | None = None
    skipped_chars: int = 0


@dataclass(frozen=True)
class LineSettings:
    margin_ms: int  # added to both sides of every window
    spell: Callable[[str], str]  # the text to force for a lyric line


def _ms_to_samples(ms: int) -> int:
    return ms * SAMPLE_RATE // MS_PER_SECOND


def cut_window(window: Window, margin_ms: int, total_samples: int) -> Cut:
    """The samples of `window` widened by `margin_ms` on both sides, within the audio."""
    start_ms = max(0, window.start_ms - margin_ms)
    return Cut(
        start_ms=start_ms,
        start=_ms_to_samples(start_ms),
        stop=min(total_samples, _ms_to_samples(window.end_ms + margin_ms)),
    )


def frame_boundary_ms(window_start_ms: int, frame: int) -> int:
    """Boundary `frame` of a cut that starts at `window_start_ms`, in ms on the audio's timeline.

    Frame k hears 25 ms from 20 * k ms; the boundary is 10 ms before the frame's
    center, which is 20 * k + 2 ms (2.5 ms rounded down) into the cut. All integers.
    """
    offset = FRAME_SAMPLES * frame + _BOUNDARY_OFFSET_SAMPLES
    return window_start_ms + offset * MS_PER_SECOND // SAMPLE_RATE


def span_log_ratio(
    log_probs: LogProbs,
    tokens: Sequence[int],
    spans: Sequence[TokenSpan],
    blank: int,
) -> float:
    """Per-frame log likelihood ratio of the forced path to the best path, where the line is sung.

    The range runs from the first token's first frame to the last token's last
    frame; the silence outside it is left out so it does not dilute the value.
    The forced path is the spans plus blank in every other frame. Never positive.
    """
    first = spans[0].start
    last = spans[-1].end
    labels = np.full(last - first, blank, dtype=np.intp)
    for token, span in zip(tokens, spans, strict=True):
        labels[span.start - first : span.end - first] = token
    section = log_probs[first:last].astype(np.float64)
    forced = float(section[np.arange(last - first), labels].sum())
    best = float(section.max(axis=1).sum())
    return min(0.0, (forced - best) / (last - first))


def refine_line(
    audio: Audio,
    model: Aligner,
    line: str,
    window: Window | None,
    settings: LineSettings,
) -> RefinedLine:
    """Force one lyric line onto its window. `audio` is the whole 16 kHz mono recording.

    The line is spelled with `settings.spell` and turned into tokens before the window is
    looked at, so the number of characters left out of the forcing is known
    whatever the outcome (`no_window` aside).
    """
    if window is None:
        return RefinedLine("no_window")
    encoded = model.vocab.encode(settings.spell(line))
    skipped = len(encoded.skipped)
    if not encoded.ids:
        return RefinedLine("no_text", skipped_chars=skipped)
    cut = cut_window(window, settings.margin_ms, audio.shape[0])
    if cut.samples > _ms_to_samples(MAX_WINDOW_MS):
        return RefinedLine("too_long", skipped_chars=skipped)
    if cut.samples < MIN_SAMPLES:
        return RefinedLine("too_short", skipped_chars=skipped)
    log_probs = model.log_probs(audio[cut.start : cut.stop])
    try:
        alignment = align_ctc(log_probs, encoded.ids, BLANK)
    except CtcAlignmentError:
        return RefinedLine("too_short", skipped_chars=skipped)
    return RefinedLine(
        "refined",
        start_ms=frame_boundary_ms(cut.start_ms, alignment.spans[0].start),
        end_ms=frame_boundary_ms(cut.start_ms, alignment.spans[-1].end),
        log_ratio=span_log_ratio(log_probs, encoded.ids, alignment.spans, BLANK),
        skipped_chars=skipped,
    )


class _Window(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_ms: _Milliseconds = Field(alias="startMs")
    end_ms: _Milliseconds = Field(alias="endMs")

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("endMs is before startMs")
        return self


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audio: _Path
    model: _Path
    lyrics: list[StrictStr]
    windows: list[_Window | None]
    spelling: Literal["surface", "kana"]
    ignored: list[Annotated[StrictStr, StringConstraints(min_length=1, max_length=1)]]
    margin_ms: _Milliseconds = Field(alias="marginMs")

    @model_validator(mode="after")
    def _one_window_per_line(self) -> Self:
        if len(self.windows) != len(self.lyrics):
            raise ValueError(
                f"windows has {len(self.windows)} entries but lyrics has {len(self.lyrics)}"
            )
        return self

    @model_validator(mode="after")
    def _ignored_are_unique(self) -> Self:
        if len(set(self.ignored)) != len(self.ignored):
            raise ValueError("ignored has duplicate characters")
        return self


def load_char_model(path: Path) -> Aligner:
    return CharCtcModel(path)


def decode_mono_16k(path: Path) -> Audio:
    """The first audio stream of `path` as 16 kHz mono float32, `[n]`."""
    mono: Audio = decode_audio(path, sample_rate=SAMPLE_RATE, channels=1)[0]
    return mono


def make_refine(
    reader_factory: Callable[[], Reader],
    *,
    decoder: Decoder = decode_mono_16k,
    model_loader: ModelLoader = load_char_model,
) -> Callable[["Session", Mapping[str, object]], dict[str, object]]:
    """The handler.

    The reader is made the first time a line is read as kana, and kept. Only the
    most recently used model is kept, as in `separate`: it is loaded again when
    another directory is used or when the model file's modification time or
    size changes.
    """
    readers: list[Reader] = []
    models = LatestModel(model_loader, lambda directory: f"the model in {directory}")

    def refine(session: "Session", params: Mapping[str, object]) -> dict[str, object]:
        parsed = _parse(params)
        audio_path = resolve_path(parsed.audio, "audio")
        model_dir = resolve_path(parsed.model, "model")
        check_input_file(audio_path, "audio")
        model_state = model_file_state(model_dir / MODEL_FILE)

        session.progress(STAGE, 0.0, None)
        audio = decoder(audio_path)
        if audio.shape[0] == 0:
            raise ProtocolError("audio_unreadable", f"{audio_path.name} has no audio samples")
        model = models.get(model_dir, model_state)

        ignored = frozenset(parsed.ignored)

        def spell(line: str) -> str:
            if parsed.spelling == "surface":
                return surface_text(line, ignored)
            if not readers:
                readers.append(reader_factory())
            return kana_text(line, readers[0], ignored)

        settings = LineSettings(margin_ms=parsed.margin_ms, spell=spell)
        total = len(parsed.lyrics)
        lines: list[dict[str, object]] = []
        for done, (text, window) in enumerate(zip(parsed.lyrics, parsed.windows, strict=True), 1):
            refined = refine_line(
                audio,
                model,
                text,
                None if window is None else Window(window.start_ms, window.end_ms),
                settings,
            )
            lines.append(_wire(refined))
            session.progress(STAGE, done / total, None)
        return {"lines": lines}

    return refine


def _wire(line: RefinedLine) -> dict[str, object]:
    return {
        "status": line.status,
        "startMs": line.start_ms,
        "endMs": line.end_ms,
        "logRatio": line.log_ratio,
        "skippedChars": line.skipped_chars,
    }


def _parse(params: Mapping[str, object]) -> _Params:
    try:
        return _Params.model_validate(params)
    except ValidationError as exc:
        problems = describe_validation_error(exc)
        raise ProtocolError(
            "invalid_request", f"refine params do not match the schema ({problems})"
        ) from None
