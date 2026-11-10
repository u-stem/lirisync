"""Model-independent CTC forced alignment (Viterbi).

Given per-frame log-probabilities from a character or phoneme CTC model and a
known token sequence, find the most likely frame-by-frame path that spells the
tokens, and report where each token sits. The forced path's log-likelihood
against the unconstrained best path gives a confidence (a likelihood ratio).

This module only does the dynamic program. Loading a model and converting
frames to milliseconds belong to the callers.
"""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

_LOG_PROBS_NDIM = 2


class CtcAlignmentError(ValueError):
    """The input cannot be aligned: malformed, too short, or impossible."""


@dataclass(frozen=True)
class TokenSpan:
    start: int  # first frame on this token's (non-blank) state
    end: int  # exclusive


@dataclass(frozen=True)
class CtcAlignment:
    spans: tuple[TokenSpan, ...]  # one per input token, in order
    log_likelihood: float  # sum of log-probs along the forced path
    best_log_likelihood: float  # unconstrained best path: sum of per-frame maxima
    frames: int

    @property
    def log_ratio_per_frame(self) -> float:
        """Per-frame log likelihood ratio of the forced path to the best path (<= 0)."""
        return (self.log_likelihood - self.best_log_likelihood) / self.frames


def align_ctc(
    log_probs: npt.NDArray[np.float32], tokens: Sequence[int], blank: int
) -> CtcAlignment:
    """Force-align `tokens` to `log_probs` of shape [T, V] (already log-softmaxed).

    Works on the standard extended sequence of 2L+1 states (blank, token 0,
    blank, token 1, ..., blank). A path may stay, advance by one state, or skip
    a blank (advance by two) when the state it lands on is a token that differs
    from the token two states back. It starts in state 0 or 1 and ends in the
    last or second-to-last state.

    Ties are broken deterministically: at each frame the predecessor preference
    is stay, then advance by one, then skip; at the end the final blank state
    wins over the last token state. Equal-scoring paths therefore resolve toward
    the earliest token placements, with the last token's span closing first.
    """
    values = _validated_log_probs(log_probs)
    frames, vocab = values.shape
    token_ids = _validated_tokens(tokens, blank, vocab)
    needed = len(token_ids) + sum(1 for a, b in itertools.pairwise(token_ids) if a == b)
    if frames < needed:
        raise CtcAlignmentError(f"too few frames: need at least {needed}, got {frames}")

    states = 2 * len(token_ids) + 1
    labels = np.full(states, blank, dtype=np.intp)
    labels[1::2] = token_ids
    # A skip lands on a token state, and is legal only if the token two states
    # back (the previous token) differs; equal neighbours must pass a blank.
    skip_allowed = np.zeros(states, dtype=np.bool_)
    skip_allowed[3::2] = labels[3::2] != labels[1:-2:2]

    # Emissions are gathered one frame at a time: a [T, 2L+1] float64 table
    # would dwarf the int8 backpointers on a long window.
    neg_inf = -np.inf
    scores = np.full(states, neg_inf, dtype=np.float64)
    scores[:2] = values[0, labels[:2]]
    # Per frame and state: how many states back the best predecessor is (0, 1, 2).
    back = np.zeros((frames, states), dtype=np.int8)
    candidates = np.full((3, states), neg_inf, dtype=np.float64)
    for t in range(1, frames):
        candidates[0] = scores
        candidates[1, 1:] = scores[:-1]
        candidates[2, 2:] = np.where(skip_allowed[2:], scores[:-2], neg_inf)
        choice = candidates.argmax(axis=0)  # first maximum: stay > advance > skip
        back[t] = choice
        scores = candidates[choice, np.arange(states)] + values[t, labels]

    state = states - 1 if scores[states - 1] >= scores[states - 2] else states - 2
    log_likelihood = float(scores[state])
    if log_likelihood == neg_inf:
        raise CtcAlignmentError("the token sequence is impossible under these log-probs")

    path = np.empty(frames, dtype=np.intp)
    path[frames - 1] = state
    for t in range(frames - 1, 0, -1):
        state -= int(back[t, state])
        path[t - 1] = state

    spans = []
    for index in range(len(token_ids)):
        on_token = np.flatnonzero(path == 2 * index + 1)
        spans.append(TokenSpan(int(on_token[0]), int(on_token[-1]) + 1))
    return CtcAlignment(
        spans=tuple(spans),
        log_likelihood=log_likelihood,
        best_log_likelihood=float(values.max(axis=1).sum()),
        frames=frames,
    )


def _validated_log_probs(log_probs: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
    if log_probs.ndim != _LOG_PROBS_NDIM:
        raise CtcAlignmentError(f"log_probs must be 2-dimensional, got {log_probs.ndim}")
    values = log_probs.astype(np.float64)
    # -inf is a legitimate log-probability; NaN and +inf are not.
    if bool(np.isnan(values).any()) or bool(np.isposinf(values).any()):
        raise CtcAlignmentError("log_probs contains NaN or +inf")
    return values


def _validated_tokens(tokens: Sequence[int], blank: int, vocab: int) -> list[int]:
    if not 0 <= blank < vocab:
        raise CtcAlignmentError(f"blank {blank} is outside the vocabulary of size {vocab}")
    token_ids = list(tokens)
    if not token_ids:
        raise CtcAlignmentError("tokens is empty")
    for token in token_ids:
        if not 0 <= token < vocab:
            raise CtcAlignmentError(f"token {token} is outside the vocabulary of size {vocab}")
        if token == blank:
            raise CtcAlignmentError("tokens must not contain the blank")
    return token_ids
