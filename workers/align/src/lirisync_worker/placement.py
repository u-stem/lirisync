"""First stage of alignment: place each lyric line on the timeline.

All sung lyric lines are read as kana and joined into one sequence; all ASR
words likewise into another. The two are aligned as wholes (`seqalign`), so
each lyric character either pairs with an ASR character or sits in a gap. A
line's place follows from its paired characters: it starts at the word its
first paired character came from and ends at the word of its last. The share
of its characters that pair exactly is the match ratio, which is evidence
independent of the lyrics because the ASR never saw them.

Aligning wholes rather than comparing line against segment matters for
repeated choruses: context on both sides decides which repetition a line is,
and the ASR's word times are used directly instead of segment spans.

A line below the minimum ratio is unmatched and gets no time. Times are integer
milliseconds; float seconds from the ASR are converted before this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from lirisync_worker.match_text import Reader, is_symbol_only, reading_chars
from lirisync_worker.seqalign import Scoring, align


@dataclass(frozen=True)
class Word:
    start: int
    end: int
    text: str


type LineStatus = Literal["anchor", "unmatched", "not_sung"]


@dataclass(frozen=True)
class PlacedLine:
    status: LineStatus
    start: int | None
    end: int | None
    match_ratio: float
    # True when the alignment could equally have put this line elsewhere: a
    # missed repetition of identical neighbouring lines (see _ambiguous_lines).
    ambiguous: bool = False


@dataclass(frozen=True)
class PlacementOptions:
    ignored: frozenset[str] = frozenset()
    # Initial value, to be tuned on the evaluation set.
    min_match_ratio: float = 0.4
    scoring: Scoring = field(default_factory=Scoring)


def place_lines(
    lyrics: Sequence[str],
    words: Sequence[Word],
    read: Reader,
    options: PlacementOptions | None = None,
) -> list[PlacedLine]:
    """One result per lyric line, in order. Blank and symbol-only lines are
    `not_sung` and take no part in the alignment."""
    options = options or PlacementOptions()
    sung = [i for i, line in enumerate(lyrics) if not is_symbol_only(line, options.ignored)]
    # Lines are read one at a time: a line break is a real boundary, unlike the
    # boundaries between ASR word fragments.
    readings = {
        i: "".join(ch for ch, _ in reading_chars([lyrics[i]], read, options.ignored)) for i in sung
    }
    lyric_text = "".join(readings[i] for i in sung)
    lyric_owner = [i for i in sung for _ in readings[i]]
    heard = reading_chars([w.text for w in words], read, options.ignored)
    heard_text = "".join(ch for ch, _ in heard)
    mapping = align(lyric_text, heard_text, options.scoring)

    pairs: dict[int, list[tuple[int, bool]]] = {i: [] for i in sung}
    for position, target in enumerate(mapping):
        if target is not None:
            exact = lyric_text[position] == heard_text[target]
            pairs[lyric_owner[position]].append((heard[target][1], exact))

    results: list[PlacedLine] = [PlacedLine("not_sung", None, None, 0.0) for _ in lyrics]
    for i in sung:
        length = len(readings[i])
        matched = sum(1 for _, exact in pairs[i] if exact)
        ratio = matched / length if length else 0.0
        if not pairs[i] or ratio < options.min_match_ratio:
            results[i] = PlacedLine("unmatched", None, None, ratio)
            continue
        first_word, last_word = pairs[i][0][0], pairs[i][-1][0]
        results[i] = PlacedLine("anchor", words[first_word].start, words[last_word].end, ratio)

    for i in _ambiguous_lines(sung, readings, results):
        line = results[i]
        results[i] = PlacedLine(line.status, line.start, line.end, line.match_ratio, ambiguous=True)
    return results


def _ambiguous_lines(
    sung: Sequence[int], readings: dict[int, str], results: Sequence[PlacedLine]
) -> set[int]:
    """Lines whose placement an equally good alignment would swap.

    A run of unmatched lines [i, i + k) can slide one line right at no cost
    exactly when line i reads the same as line i + k (and one line left when
    line i - 1 reads the same as line i + k - 1); any longer slide implies the
    one-line slide. Each slide that keeps the condition reaches one more line
    that might be the missed one. So "A B A" with the last A missed is not
    ambiguous (order fixes it), but "A A" or "A B A B" with one copy missed is.
    """
    texts = [readings[i] for i in sung]
    unmatched = [results[i].status == "unmatched" for i in sung]
    marked: set[int] = set()
    start = 0
    while start < len(sung):
        if not unmatched[start]:
            start += 1
            continue
        end = start
        while end < len(sung) and unmatched[end]:
            end += 1
        reach: set[int] = set()
        step = 0
        while end + step < len(sung) and texts[start + step] == texts[end + step]:
            reach.add(end + step)
            step += 1
        step = 1
        while start - step >= 0 and texts[start - step] == texts[end - step]:
            reach.add(start - step)
            step += 1
        if reach:
            marked.update(reach, range(start, end))
        start = end
    return {sung[k] for k in marked}
