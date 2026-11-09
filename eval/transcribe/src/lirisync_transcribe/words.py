"""Turns faster-whisper words into the eval set's ASR word records (pure)."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class WordLike(Protocol):
    """The part of faster-whisper's ``Word`` that this module reads."""

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def word(self) -> str: ...


def to_ms(seconds: float) -> int:
    """Rounds a time in seconds to integer milliseconds."""
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError(f"seconds must be a finite number >= 0, got {seconds!r}")
    return round(seconds * 1000)


@dataclass(frozen=True)
class AsrWords:
    """Word records plus how many starts had to be clamped to keep the order."""

    words: list[dict[str, int | str]]
    clamped_starts: int


def asr_words(words: Iterable[WordLike]) -> AsrWords:
    """Converts words to ``{"startMs", "endMs", "text"}`` records.

    The text is kept verbatim: Whisper puts a space before most words, and the
    aligner joins the texts as they are. Order defines the transcript, so the
    words are never sorted. Whisper's word times can step backwards a little;
    such a start is clamped to the previous word's start (and counted), so that
    one odd word does not lose the whole song.
    """
    records: list[dict[str, int | str]] = []
    clamped = 0
    previous_start = 0
    for number, word in enumerate(words, start=1):
        try:
            start = to_ms(word.start)
            end = to_ms(word.end)
        except ValueError as error:
            raise ValueError(f"word {number}: {error}") from error
        if start < previous_start:
            start = previous_start
            clamped += 1
        # Rounding or clamping can put an end before its start.
        end = max(end, start)
        records.append({"startMs": start, "endMs": end, "text": word.word})
        previous_start = start
    return AsrWords(words=records, clamped_starts=clamped)
