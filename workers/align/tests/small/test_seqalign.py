import itertools
import math
import random

import pytest

from lirisync_worker.seqalign import AlignmentTooLargeError, Scoring, align


def test_identical_sequences_align_one_to_one() -> None:
    assert align("あいうえお", "あいうえお") == [0, 1, 2, 3, 4]


def test_a_substitution_stays_aligned() -> None:
    assert align("きみをあいしてる", "きみおあいしてる") == [0, 1, 2, 3, 4, 5, 6, 7]


def test_extra_characters_in_the_second_sequence_are_skipped() -> None:
    assert align("あいうえお", "あいxxxxxxうえお") == [0, 1, 8, 9, 10]


def test_characters_missing_from_the_second_sequence_stay_unaligned() -> None:
    result = align("あいかきくけこさしすうえお", "あいうえお")
    assert result == [0, 1, None, None, None, None, None, None, None, None, 2, 3, 4]


def test_leading_and_trailing_extras_are_free() -> None:
    assert align("うえお", "xxxxうえおyyyy") == [4, 5, 6]


def test_unrelated_sequences_align_nothing() -> None:
    assert align("かきくけこ", "さしすせそ") == [None] * 5


def test_an_empty_sequence_aligns_nothing() -> None:
    assert align("あい", "") == [None, None]


# Property check against a plain, unvectorized Gotoh with the same free ends.

_SCORING = Scoring()


def _gap(length: int) -> float:
    return 0.0 if length == 0 else _SCORING.gap_open + _SCORING.gap_extend * (length - 1)


def _reference_best(first: str, second: str) -> float:
    """Best score by the textbook three-matrix recurrence, cell by cell."""
    n, m = len(first), len(second)
    neg = float("-inf")
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    vertical = [[neg] * (m + 1) for _ in range(n + 1)]
    horizontal = [[neg] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            vertical[i][j] = max(
                best[i - 1][j] - _SCORING.gap_open, vertical[i - 1][j] - _SCORING.gap_extend
            )
            horizontal[i][j] = max(
                best[i][j - 1] - _SCORING.gap_open, horizontal[i][j - 1] - _SCORING.gap_extend
            )
            pair = _SCORING.match if first[i - 1] == second[j - 1] else _SCORING.mismatch
            best[i][j] = max(best[i - 1][j - 1] + pair, vertical[i][j], horizontal[i][j])
    ends = [best[i][m] for i in range(n + 1)] + [best[n][j] for j in range(m + 1)]
    return max(ends)


def _score_of(first: str, second: str, mapping: list[int | None]) -> float:
    """Score of the alignment `mapping` describes, under the same free ends."""
    pairs = [(i, j) for i, j in enumerate(mapping) if j is not None]
    if not pairs:
        return 0.0
    total = sum(_SCORING.match if first[i] == second[j] else _SCORING.mismatch for i, j in pairs)
    (first_i, first_j), (last_i, last_j) = pairs[0], pairs[-1]
    lead = 0.0 if first_i == 0 or first_j == 0 else min(_gap(first_i), _gap(first_j))
    rest_i, rest_j = len(first) - 1 - last_i, len(second) - 1 - last_j
    trail = 0.0 if rest_i == 0 or rest_j == 0 else min(_gap(rest_i), _gap(rest_j))
    inner = sum(
        _gap(i2 - i1 - 1) + _gap(j2 - j1 - 1) for (i1, j1), (i2, j2) in itertools.pairwise(pairs)
    )
    return total - lead - trail - inner


def test_alignment_scores_match_the_reference_on_random_inputs() -> None:
    generator = random.Random(20261108)
    mismatches = []
    for _ in range(400):
        first = "".join(generator.choice("あいう") for _ in range(generator.randint(0, 8)))
        second = "".join(generator.choice("あいう") for _ in range(generator.randint(0, 8)))
        got = _score_of(first, second, align(first, second, _SCORING))
        want = _reference_best(first, second)
        if not math.isclose(got, want):
            mismatches.append((first, second, got, want))
    assert mismatches == []


def test_an_oversized_alignment_is_refused() -> None:
    with pytest.raises(AlignmentTooLargeError):
        align("あ" * 10, "い" * 10, _SCORING, max_cells=50)
