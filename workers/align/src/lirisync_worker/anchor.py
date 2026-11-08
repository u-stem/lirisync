"""Anchor known lyric lines onto ASR segments by forward fuzzy matching.

Lines are grouped into units of `pairing` lines. Each unit takes the most
similar segment among the next `window` segments after the last one taken,
if it clears a script-aware threshold; a multi-line unit is then split at the
breaths between its words. Matching only moves forward, so repeated choruses
take their repetitions in order.

The approach comes from lyric-align's published measurements, which found the
obvious alternatives worse on repeated choruses: a globally optimal monotone
assignment, a timing prior, candidates spanning two segments, and unit sizes
chosen per step. None of them is used here.

A line that cannot be placed stays unmatched: no time is invented for it.
All times are integer milliseconds; float seconds from the ASR are converted
before they reach this module.
"""

import itertools
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from rapidfuzz.distance import Indel

from lirisync_worker.match_text import MatchForms, Reader, is_symbol_only, match_forms


@dataclass(frozen=True)
class Word:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    text: str
    words: tuple[Word, ...] = ()


type LineStatus = Literal["anchor", "unmatched", "not_sung"]


@dataclass(frozen=True)
class AnchoredLine:
    status: LineStatus
    start: int | None
    end: int | None
    score: float


CJK_THRESHOLD = 0.25
LATIN_THRESHOLD = 0.5
_CJK_SHARE_FOR_LOW_THRESHOLD = 0.2
MAX_PAIRING = 3
DEFAULT_WINDOW = 4
_BREATH_SEARCH = 3


def similarity(a: MatchForms, b: MatchForms) -> float:
    """Character similarity in [0, 1], the better of surface and reading.

    Indel similarity is 2 * LCS / (len(a) + len(b)), the same ratio difflib's
    SequenceMatcher approximates, so thresholds measured with difflib carry
    over.
    """
    return max(
        Indel.normalized_similarity(a.surface, b.surface),
        Indel.normalized_similarity(a.reading, b.reading),
    )


def _is_cjk(ch: str) -> bool:
    name = unicodedata.name(ch, "")
    return name.startswith(("CJK", "HIRAGANA", "KATAKANA", "HALFWIDTH KATAKANA"))


def default_threshold(surfaces: Sequence[str]) -> float:
    """0.25 for Japanese/Chinese lyrics, 0.5 for Latin-script lyrics.

    Chance similarity depends on the size of the character inventory: two
    unrelated English lines share enough letters to score about 0.3, while a
    true Japanese match against sung ASR can drop to about 0.26 (measured by
    lyric-align). One floor cannot serve both.
    """
    chars = "".join(surfaces)
    if not chars:
        return LATIN_THRESHOLD
    cjk_share = sum(1 for ch in chars if _is_cjk(ch)) / len(chars)
    return CJK_THRESHOLD if cjk_share >= _CJK_SHARE_FOR_LOW_THRESHOLD else LATIN_THRESHOLD


def auto_pairing(*, lines: int, segments: int) -> int:
    """Lyric lines the ASR merged into one segment, rounded, from 1 to 3.

    Pairing is a property of the ASR's segmentation, not of the song: medium
    merges about two sung lines per segment while large-v3 splits finer. Above
    three the ASR has stopped producing line-like segments, and the fix is
    vocal separation rather than a wider unit.
    """
    if segments == 0:
        return 1
    return max(1, min(MAX_PAIRING, round(lines / segments)))


def _silence_before(words: Sequence[Word], index: int) -> int:
    return words[index].start - words[index - 1].end


def _choose_cut(words: Sequence[Word], aim: int, earliest: int, latest: int) -> int:
    """The boundary in [earliest, latest] near `aim` with the longest silence.

    Only boundaries within `_BREATH_SEARCH` words of `aim` are considered, so a
    long pause elsewhere in the segment (an interlude) cannot pull the cut away
    from where the character counts put it. Ties go to the earlier boundary.
    """
    near = range(max(earliest, aim - _BREATH_SEARCH), min(latest, aim + _BREATH_SEARCH) + 1)
    if not near:
        return max(earliest, min(aim, latest))
    return max(near, key=lambda index: (_silence_before(words, index), -index))


def split_by_breath(words: Sequence[Word], weights: Sequence[int]) -> list[list[Word]]:
    """Partition `words` into one group per line, cutting at breaths.

    `weights` are the lines' character counts; each cut aims at the word index
    their running share implies and then moves to the longest silence close by.
    Groups may be empty when there are fewer words than lines.
    """
    if not weights:
        return []
    if len(weights) == 1 or len(words) <= 1:
        return [list(words), *([] for _ in weights[1:])]
    total = sum(weights) or 1
    bounds = [0]
    share = 0
    for line, weight in enumerate(weights[:-1], start=1):
        share += weight
        aim = round(len(words) * share / total)
        # Leave at least one word for each line after this cut.
        latest = len(words) - (len(weights) - line)
        bounds.append(max(bounds[-1], _choose_cut(words, aim, bounds[-1] + 1, latest)))
    bounds.append(len(words))
    return [list(words[a:b]) for a, b in itertools.pairwise(bounds)]


def _join(forms: Sequence[MatchForms]) -> MatchForms:
    return MatchForms(
        surface="".join(f.surface for f in forms),
        reading="".join(f.reading for f in forms),
    )


def _best_segment(
    unit: MatchForms, heard: Sequence[MatchForms], cursor: int, window: int
) -> tuple[int | None, float]:
    """Index and score of the most similar segment in the look-ahead window.

    The earliest segment wins a tie, so a repeated line takes the nearer
    repetition and leaves the later one for the next occurrence.
    """
    candidates = range(cursor, min(cursor + window, len(heard)))
    scored = [(similarity(unit, heard[index]), -index) for index in candidates]
    if not scored:
        return None, 0.0
    score, negative_index = max(scored)
    return (-negative_index, score) if score > 0 else (None, score)


def _place_unit(
    unit: Sequence[int], forms: Mapping[int, MatchForms], seg: Segment, score: float
) -> dict[int, AnchoredLine]:
    if len(unit) == 1 or not seg.words:
        return {i: AnchoredLine("anchor", seg.start, seg.end, score) for i in unit}
    groups = split_by_breath(seg.words, [len(forms[i].surface) for i in unit])
    placed: dict[int, AnchoredLine] = {}
    for i, group in zip(unit, groups, strict=True):
        if group:
            placed[i] = AnchoredLine("anchor", group[0].start, group[-1].end, score)
        else:
            placed[i] = AnchoredLine("anchor", seg.start, seg.end, score)
    return placed


@dataclass(frozen=True)
class AnchorOptions:
    """Tuning for `anchor_lines`. `None` picks the automatic value."""

    ignored: frozenset[str] = frozenset()
    pairing: int | None = None
    threshold: float | None = None
    window: int = DEFAULT_WINDOW


def anchor_lines(
    lyrics: Sequence[str],
    segments: Sequence[Segment],
    read: Reader,
    options: AnchorOptions | None = None,
) -> list[AnchoredLine]:
    """One result per lyric line, in order.

    Blank and symbol-only lines are `not_sung` and take no part in matching.
    `pairing` and `threshold` default to `auto_pairing` and
    `default_threshold`.
    """
    options = options or AnchorOptions()
    ignored = options.ignored
    sung = [i for i, line in enumerate(lyrics) if not is_symbol_only(line, ignored)]
    forms = {i: match_forms(lyrics[i], read, ignored) for i in sung}
    heard = [match_forms(seg.text, read, ignored) for seg in segments]
    threshold = options.threshold
    if threshold is None:
        threshold = default_threshold([forms[i].surface for i in sung])
    pairing = options.pairing
    if pairing is None:
        pairing = auto_pairing(lines=len(sung), segments=len(segments))
    pairing = max(1, pairing)

    results: dict[int, AnchoredLine] = {
        i: AnchoredLine("not_sung", None, None, 0.0) for i in range(len(lyrics)) if i not in forms
    }
    cursor = 0
    for first in range(0, len(sung), pairing):
        unit = sung[first : first + pairing]
        index, score = _best_segment(_join([forms[i] for i in unit]), heard, cursor, options.window)
        if index is None or score <= threshold:
            # Unmatched: no time is invented, and the cursor stays put so the
            # next unit can still take the segment this one missed.
            results.update({i: AnchoredLine("unmatched", None, None, score) for i in unit})
            continue
        cursor = index + 1
        results.update(_place_unit(unit, forms, segments[index], score))
    return [results[i] for i in range(len(lyrics))]
