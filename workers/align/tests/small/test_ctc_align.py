import itertools
import math
import random

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.ctc_align import CtcAlignmentError, TokenSpan, align_ctc

BLANK = 0


def _peaked(labels: list[int], vocab: int) -> npt.NDArray[np.float32]:
    """Log-probs that put almost all mass on `labels[t]` at frame t."""
    logits = np.zeros((len(labels), vocab), dtype=np.float64)
    for frame, label in enumerate(labels):
        logits[frame, label] = 10.0
    shifted = logits - logits.max(axis=1, keepdims=True)
    log_probs = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    return log_probs.astype(np.float32)


def _uniform(frames: int, vocab: int) -> npt.NDArray[np.float32]:
    return np.full((frames, vocab), -math.log(vocab), dtype=np.float32)


def test_a_single_token_span_covers_its_peak_frames() -> None:
    log_probs = _peaked([BLANK, 1, 1, 1, BLANK], 3)
    assert align_ctc(log_probs, [1], BLANK).spans == (TokenSpan(1, 4),)


def test_leading_and_trailing_blank_frames_stay_out_of_the_span() -> None:
    log_probs = _peaked([BLANK, BLANK, 2, BLANK, BLANK, BLANK], 3)
    span = align_ctc(log_probs, [2], BLANK).spans[0]
    assert (span.start, span.end) == (2, 3)


def test_blank_frames_between_tokens_belong_to_neither_span() -> None:
    log_probs = _peaked([1, 1, BLANK, BLANK, 2, 2, 2], 3)
    assert align_ctc(log_probs, [1, 2], BLANK).spans == (TokenSpan(0, 2), TokenSpan(4, 7))


def test_there_is_one_span_per_token_in_order() -> None:
    log_probs = _peaked([1, 2, 3, 1], 4)
    assert len(align_ctc(log_probs, [1, 2, 3, 1], BLANK).spans) == 4


def test_adjacent_equal_tokens_get_separate_spans_around_a_blank() -> None:
    log_probs = _peaked([1, 1, BLANK, 1, 1], 2)
    assert align_ctc(log_probs, [1, 1], BLANK).spans == (TokenSpan(0, 2), TokenSpan(3, 5))


def test_adjacent_equal_tokens_pass_with_exactly_the_required_frames() -> None:
    log_probs = _uniform(3, 2)
    assert align_ctc(log_probs, [1, 1], BLANK).spans == (TokenSpan(0, 1), TokenSpan(2, 3))


def test_one_frame_short_of_the_required_count_is_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="frames"):
        align_ctc(_uniform(2, 2), [1, 1], BLANK)


def test_distinct_tokens_need_no_blank_between_them() -> None:
    log_probs = _peaked([1, 2], 3)
    assert align_ctc(log_probs, [1, 2], BLANK).spans == (TokenSpan(0, 1), TokenSpan(1, 2))


def test_a_nonzero_blank_index_is_honoured() -> None:
    log_probs = _peaked([2, 0, 0, 2], 3)
    assert align_ctc(log_probs, [0], 2).spans == (TokenSpan(1, 3),)


def test_a_tie_between_equal_paths_places_the_token_as_early_as_possible() -> None:
    # Every path is equally likely; the documented rule picks the earliest span.
    assert align_ctc(_uniform(3, 2), [1], BLANK).spans == (TokenSpan(0, 1),)


def test_negative_infinity_log_probs_are_accepted() -> None:
    log_probs = _peaked([BLANK, 1, BLANK], 2)
    log_probs[0, 1] = -np.inf
    assert align_ctc(log_probs, [1], BLANK).spans == (TokenSpan(1, 2),)


def test_the_frame_count_is_reported() -> None:
    assert align_ctc(_uniform(5, 3), [1], BLANK).frames == 5


def test_a_perfectly_matching_path_has_zero_log_ratio() -> None:
    log_probs = _peaked([BLANK, 1, 1, BLANK, 2], 3)
    result = align_ctc(log_probs, [1, 2], BLANK)
    assert result.log_ratio_per_frame == pytest.approx(0.0, abs=1e-9)


def test_a_mismatching_path_has_negative_log_ratio() -> None:
    log_probs = _peaked([1, 1, 1], 3)
    assert align_ctc(log_probs, [2], BLANK).log_ratio_per_frame < 0


def test_the_best_path_log_likelihood_sums_the_per_frame_maxima() -> None:
    log_probs = _uniform(4, 2)
    assert align_ctc(log_probs, [1], BLANK).best_log_likelihood == pytest.approx(
        4 * -math.log(2), abs=1e-6
    )


def test_a_one_dimensional_input_is_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="2-dimensional"):
        align_ctc(np.zeros(4, dtype=np.float32), [1], BLANK)


def test_a_nan_log_prob_is_refused() -> None:
    log_probs = _uniform(3, 2)
    log_probs[1, 0] = np.nan
    with pytest.raises(CtcAlignmentError, match="NaN"):
        align_ctc(log_probs, [1], BLANK)


def test_a_positive_infinite_log_prob_is_refused() -> None:
    log_probs = _uniform(3, 2)
    log_probs[1, 0] = np.inf
    with pytest.raises(CtcAlignmentError, match=r"\+inf"):
        align_ctc(log_probs, [1], BLANK)


def test_empty_tokens_are_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="empty"):
        align_ctc(_uniform(3, 2), [], BLANK)


def test_a_token_equal_to_blank_is_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="blank"):
        align_ctc(_uniform(4, 3), [1, BLANK], BLANK)


def test_a_token_beyond_the_vocabulary_is_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="vocabulary"):
        align_ctc(_uniform(4, 3), [3], BLANK)


def test_a_negative_token_is_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="vocabulary"):
        align_ctc(_uniform(4, 3), [-1], BLANK)


def test_a_blank_beyond_the_vocabulary_is_refused() -> None:
    with pytest.raises(CtcAlignmentError, match="blank"):
        align_ctc(_uniform(4, 3), [1], 3)


def test_an_impossible_forced_path_is_refused() -> None:
    log_probs = _uniform(1, 2)
    log_probs[0, 1] = -np.inf
    with pytest.raises(CtcAlignmentError, match="impossible"):
        align_ctc(log_probs, [1], BLANK)


# Property check against a brute-force search over every frame labelling.


def _collapse(labels: tuple[int, ...]) -> list[int]:
    """The CTC collapse: merge repeats, then drop blanks."""
    merged = [label for label, _ in itertools.groupby(labels)]
    return [label for label in merged if label != BLANK]


def _brute_force_best(log_probs: npt.NDArray[np.float32], tokens: list[int]) -> float:
    frames, vocab = log_probs.shape
    best = -math.inf
    for labels in itertools.product(range(vocab), repeat=frames):
        if _collapse(labels) == tokens:
            total = sum(float(log_probs[t, label]) for t, label in enumerate(labels))
            best = max(best, total)
    return best


def _random_log_probs(generator: random.Random, frames: int, vocab: int) -> npt.NDArray[np.float32]:
    logits = np.array(
        [[generator.gauss(0.0, 2.0) for _ in range(vocab)] for _ in range(frames)],
        dtype=np.float64,
    )
    shifted = logits - logits.max(axis=1, keepdims=True)
    return (shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))).astype(np.float32)


def _random_cases(count: int) -> list[tuple[npt.NDArray[np.float32], list[int]]]:
    """Seeded small inputs (T <= 6, V <= 4, <= 3 tokens) with enough frames."""
    generator = random.Random(20261110)
    cases: list[tuple[npt.NDArray[np.float32], list[int]]] = []
    while len(cases) < count:
        frames = generator.randint(1, 6)
        vocab = generator.randint(2, 4)
        tokens = [generator.randint(1, vocab - 1) for _ in range(generator.randint(1, 3))]
        repeats = sum(1 for a, b in itertools.pairwise(tokens) if a == b)
        if frames < len(tokens) + repeats:
            continue
        cases.append((_random_log_probs(generator, frames, vocab), tokens))
    return cases


def _path_from_spans(spans: tuple[TokenSpan, ...], tokens: list[int], frames: int) -> list[int]:
    """Frame labels implied by the spans: each span's token, blank elsewhere."""
    labels = [BLANK] * frames
    for span, token in zip(spans, tokens, strict=True):
        labels[span.start : span.end] = [token] * (span.end - span.start)
    return labels


def _spans_are_ordered(spans: tuple[TokenSpan, ...], frames: int) -> bool:
    bounds_ok = all(0 <= s.start < s.end <= frames for s in spans)
    return bounds_ok and all(a.end <= b.start for a, b in itertools.pairwise(spans))


def test_forced_log_likelihood_matches_brute_force_on_random_inputs() -> None:
    mismatches = []
    for log_probs, tokens in _random_cases(150):
        got = align_ctc(log_probs, tokens, BLANK).log_likelihood
        want = _brute_force_best(log_probs, tokens)
        if not math.isclose(got, want, abs_tol=1e-5):
            mismatches.append((log_probs.shape, tokens, got, want))
    assert mismatches == []


def test_spans_spell_a_path_with_the_reported_likelihood_on_random_inputs() -> None:
    # Spans plus "blank elsewhere" fix the path, so a backtracking error shows
    # up as disordered spans, a wrong spelling, or a different path score.
    failures = []
    for log_probs, tokens in _random_cases(150):
        result = align_ctc(log_probs, tokens, BLANK)
        frames = log_probs.shape[0]
        labels = _path_from_spans(result.spans, tokens, frames)
        score = sum(float(log_probs[t, label]) for t, label in enumerate(labels))
        if not (
            _spans_are_ordered(result.spans, frames)
            and _collapse(tuple(labels)) == tokens
            and math.isclose(score, result.log_likelihood, abs_tol=1e-5)
        ):
            failures.append((log_probs.shape, tokens, result.spans))
    assert failures == []
