"""Order-preserving alignment of two character sequences.

Gotoh's affine-gap dynamic programming, with free gaps at both ends of both
sequences: lyrics may start before the ASR picks anything up, and the ASR may
transcribe an intro or an outro the lyrics do not have. Inside, a gap costs
`gap_open` once plus `gap_extend` per character, so one long gap (a chorus the
ASR missed) is cheap while scattered single-character matches are not worth
the two gaps they need.

Rows are vectorized with NumPy. The horizontal gap state depends on the same
row, which a plain vectorization cannot express; it is computed from a running
maximum instead (see `_horizontal_gaps`), which is exact because reopening a
gap is never better than extending it when `gap_open >= gap_extend`.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Scoring:
    """Initial values, to be tuned on the evaluation set.

    A mismatch must stay cheaper than the two gaps that would replace it, so
    ASR misspellings stay aligned. It must also cost enough that skipping a
    prefix for free and pairing unrelated characters does not beat a true
    match across one gap; at -1.0 it did (see the tests).
    """

    match: float = 2.0
    mismatch: float = -1.5
    gap_open: float = 3.0
    gap_extend: float = 0.5

    def __post_init__(self) -> None:
        if self.gap_open < self.gap_extend:
            raise ValueError("gap_open must be at least gap_extend")


_NEG = -1e18

type FloatRow = npt.NDArray[np.float64]
type IntRow = npt.NDArray[np.int64]


@dataclass(frozen=True)
class _Pointers:
    """Per-cell choices kept for the traceback."""

    from_vertical: npt.NDArray[np.bool_]  # the best non-horizontal move is a gap in `second`
    from_horizontal: npt.NDArray[np.bool_]  # the cell's best is a gap in `first`
    vertical_opened: npt.NDArray[np.bool_]  # the vertical gap opens here rather than extends
    horizontal_from: npt.NDArray[np.int64]  # column the horizontal gap opened from

    @classmethod
    def empty(cls, rows: int, columns: int) -> "_Pointers":
        flags = (rows, columns)
        return cls(
            np.zeros(flags, dtype=np.bool_),
            np.zeros(flags, dtype=np.bool_),
            np.zeros(flags, dtype=np.bool_),
            np.zeros(flags, dtype=np.int64),
        )


def _codes(text: str, table: dict[str, int]) -> IntRow:
    return np.array([table.setdefault(ch, len(table)) for ch in text], dtype=np.int64)


def _horizontal_gaps(row: FloatRow, gap_open: float, gap_extend: float) -> tuple[FloatRow, IntRow]:
    """Best score ending in a gap in the first sequence, for columns 1..m.

    E[j] = max over k < j of row[k] - gap_open - gap_extend * (j - 1 - k)
         = max over k < j of (row[k] + gap_extend * k) - gap_open - gap_extend * (j - 1)
    so a running maximum of `row[k] + gap_extend * k` gives every column at
    once. Returns the scores and, for each column, the column k the gap opens
    from (the latest k on a tie, i.e. the shortest gap).
    """
    columns = np.arange(row.size, dtype=np.int64)
    shifted = row + gap_extend * columns
    running = np.maximum.accumulate(shifted)
    opened_at = np.maximum.accumulate(np.where(shifted >= running, columns, 0))
    scores = running[:-1] - gap_open - gap_extend * columns[:-1]
    return scores, opened_at[:-1]


def align(first: str, second: str, scoring: Scoring | None = None) -> list[int | None]:
    """For each character of `first`, the index it aligns to in `second`.

    `None` marks a character left in a gap. Aligned pairs may differ (a
    substitution); callers compare the characters to count exact matches.
    """
    scoring = scoring or Scoring()
    n, m = len(first), len(second)
    if n == 0 or m == 0:
        return [None] * n
    table: dict[str, int] = {}
    a, b = _codes(first, table), _codes(second, table)

    pointers = _Pointers.empty(n + 1, m + 1)

    previous = np.zeros(m + 1)  # row 0: leading gap in `first` is free
    vertical = np.full(m + 1, _NEG)
    best_score, best_cell = 0.0, (0, 0)
    for i in range(1, n + 1):
        substitution = np.where(b == a[i - 1], scoring.match, scoring.mismatch)
        diagonal = previous[:-1] + substitution
        open_vertical = previous[1:] - scoring.gap_open
        extend_vertical = vertical[1:] - scoring.gap_extend
        vertical_row = np.maximum(open_vertical, extend_vertical)
        no_horizontal = np.concatenate(([0.0], np.maximum(diagonal, vertical_row)))
        horizontal_row, opened_at = _horizontal_gaps(
            no_horizontal, scoring.gap_open, scoring.gap_extend
        )
        current = np.concatenate(([0.0], np.maximum(no_horizontal[1:], horizontal_row)))

        pointers.from_vertical[i, 1:] = vertical_row > diagonal
        pointers.from_horizontal[i, 1:] = horizontal_row > no_horizontal[1:]
        pointers.vertical_opened[i, 1:] = open_vertical >= extend_vertical
        pointers.horizontal_from[i, 1:] = opened_at
        vertical = np.concatenate(([_NEG], vertical_row))
        previous = current

        # Trailing characters of `second` are free: any cell of the last row ends.
        if current[m] > best_score:
            best_score, best_cell = float(current[m]), (i, m)
        if i == n:
            j = int(np.argmax(current))
            if current[j] > best_score:
                best_score, best_cell = float(current[j]), (i, j)

    return _trace(n, best_cell, pointers)


def _trace(n: int, cell: tuple[int, int], pointers: _Pointers) -> list[int | None]:
    mapping: list[int | None] = [None] * n
    i, j = cell
    state = "cell"
    while i > 0 and j > 0:
        if state == "cell" and pointers.from_horizontal[i, j]:
            j = int(pointers.horizontal_from[i, j])
            state = "no_horizontal"
        elif state in {"cell", "no_horizontal"} and not pointers.from_vertical[i, j]:
            mapping[i - 1] = j - 1
            i, j = i - 1, j - 1
            state = "cell"
        else:  # inside a vertical gap: first[i - 1] is left unaligned
            opened = bool(pointers.vertical_opened[i, j])
            i -= 1
            state = "cell" if opened else "vertical"
    return mapping
