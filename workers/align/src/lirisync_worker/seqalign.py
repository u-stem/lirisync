"""Order-preserving alignment of two character sequences.

Gotoh's affine-gap dynamic programming, with free gaps at both ends of both
sequences: lyrics may start before the ASR picks anything up, and the ASR may
transcribe an intro or an outro the lyrics do not have. Inside, a gap of L
characters costs `gap_open + gap_extend * (L - 1)`, so one long gap (a chorus
the ASR missed) is cheap while scattered single-character matches are not
worth the two gaps they need.

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

# The traceback keeps 5 bytes per cell. A 10-minute song is a few thousand
# characters a side (tens of MB); this cap (about 250 MB) stops an ASR that
# hallucinated for minutes from exhausting memory without saying so.
MAX_CELLS = 50_000_000

type FloatRow = npt.NDArray[np.float64]
type IntRow = npt.NDArray[np.int64]

# Bits of _Pointers.flags.
_FROM_VERTICAL = 1  # the best non-horizontal move is a gap in `second`
_FROM_HORIZONTAL = 2  # the cell's best is a gap in `first`
_VERTICAL_OPENED = 4  # the vertical gap opens here rather than extends


@dataclass(frozen=True)
class _Pointers:
    """Per-cell choices kept for the traceback."""

    flags: npt.NDArray[np.uint8]
    horizontal_from: npt.NDArray[np.int32]  # column the horizontal gap opened from

    @classmethod
    def empty(cls, rows: int, columns: int) -> "_Pointers":
        shape = (rows, columns)
        return cls(np.zeros(shape, dtype=np.uint8), np.zeros(shape, dtype=np.int32))

    def has(self, i: int, j: int, bit: int) -> bool:
        return bool(self.flags[i, j] & bit)


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


def align(
    first: str, second: str, scoring: Scoring | None = None, *, max_cells: int = MAX_CELLS
) -> list[int | None]:
    """For each character of `first`, the index it aligns to in `second`.

    `None` marks a character left in a gap. Aligned pairs may differ (a
    substitution); callers compare the characters to count exact matches.

    Raises ValueError when the table would exceed `max_cells`.
    """
    scoring = scoring or Scoring()
    n, m = len(first), len(second)
    if n == 0 or m == 0:
        return [None] * n
    if (n + 1) * (m + 1) > max_cells:
        raise ValueError(f"alignment too large: {n} x {m} characters exceeds {max_cells} cells")
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

        pointers.flags[i, 1:] = (
            np.where(vertical_row > diagonal, _FROM_VERTICAL, 0)
            | np.where(horizontal_row > no_horizontal[1:], _FROM_HORIZONTAL, 0)
            | np.where(open_vertical >= extend_vertical, _VERTICAL_OPENED, 0)
        )
        pointers.horizontal_from[i, 1:] = opened_at
        vertical = np.concatenate(([_NEG], vertical_row))
        previous = current

        # Trailing characters of either sequence are free: an alignment may end
        # in the last column (rest of `first` unaligned) or the last row (rest
        # of `second` unaligned).
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
        if state == "cell" and pointers.has(i, j, _FROM_HORIZONTAL):
            j = int(pointers.horizontal_from[i, j])
            state = "no_horizontal"
        elif state in {"cell", "no_horizontal"} and not pointers.has(i, j, _FROM_VERTICAL):
            mapping[i - 1] = j - 1
            i, j = i - 1, j - 1
            state = "cell"
        else:  # inside a vertical gap: first[i - 1] is left unaligned
            opened = pointers.has(i, j, _VERTICAL_OPENED)
            i -= 1
            state = "cell" if opened else "vertical"
    return mapping
