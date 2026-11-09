import math
from dataclasses import dataclass

import pytest

from lirisync_transcribe.words import asr_words, to_ms


@dataclass(frozen=True)
class FakeWord:
    start: float
    end: float
    word: str


def test_to_ms_rounds_to_the_nearest_millisecond() -> None:
    assert to_ms(1.2346) == 1235


def test_to_ms_accepts_zero() -> None:
    assert to_ms(0.0) == 0


def test_to_ms_does_not_drift_on_float_products() -> None:
    assert to_ms(4.1) == 4100


@pytest.mark.parametrize("seconds", [-0.001, math.nan, math.inf, -math.inf])
def test_to_ms_rejects_negative_and_non_finite_seconds(seconds: float) -> None:
    with pytest.raises(ValueError, match="seconds"):
        to_ms(seconds)


def test_asr_words_converts_to_the_protocol_shape() -> None:
    words = [FakeWord(12.3, 12.9, "風が")]

    assert asr_words(words).words == [{"startMs": 12300, "endMs": 12900, "text": "風が"}]


def test_asr_words_keeps_the_text_verbatim() -> None:
    words = [FakeWord(0.0, 0.5, " line ")]

    assert asr_words(words).words[0]["text"] == " line "


def test_asr_words_returns_an_empty_list_for_no_words() -> None:
    assert asr_words([]).words == []


def test_asr_words_clamps_an_end_that_rounds_before_the_start() -> None:
    words = [FakeWord(1.0006, 1.0004, "a")]

    assert asr_words(words).words == [{"startMs": 1001, "endMs": 1001, "text": "a"}]


def test_asr_words_allows_equal_and_overlapping_starts() -> None:
    words = [FakeWord(1.0, 2.0, "a"), FakeWord(1.0, 1.5, "b"), FakeWord(1.2, 3.0, "c")]

    assert [w["startMs"] for w in asr_words(words).words] == [1000, 1000, 1200]


def test_asr_words_clamps_a_start_that_goes_backwards_to_the_previous_start() -> None:
    words = [FakeWord(2.0, 2.5, "a"), FakeWord(1.0, 1.5, "b")]

    assert [w["startMs"] for w in asr_words(words).words] == [2000, 2000]


def test_asr_words_keeps_the_end_at_or_after_a_clamped_start() -> None:
    words = [FakeWord(2.0, 2.5, "a"), FakeWord(1.0, 1.5, "b")]

    assert asr_words(words).words[1]["endMs"] == 2000


def test_asr_words_keeps_the_text_of_a_clamped_word() -> None:
    words = [FakeWord(2.0, 2.5, "a"), FakeWord(1.0, 1.5, " b")]

    assert asr_words(words).words[1]["text"] == " b"


def test_asr_words_counts_the_clamped_starts() -> None:
    words = [FakeWord(2.0, 2.5, "a"), FakeWord(1.0, 1.5, "b"), FakeWord(0.5, 0.9, "c")]

    assert asr_words(words).clamped_starts == 2


def test_asr_words_counts_no_clamps_for_ordered_words() -> None:
    words = [FakeWord(1.0, 2.0, "a"), FakeWord(1.0, 1.5, "b"), FakeWord(1.2, 3.0, "c")]

    assert asr_words(words).clamped_starts == 0


def test_asr_words_does_not_count_a_clamp_for_the_rounding_of_a_start() -> None:
    words = [FakeWord(1.0004, 2.0, "a"), FakeWord(1.0002, 2.0, "b")]

    assert asr_words(words).clamped_starts == 0


def test_asr_words_does_not_sort_its_input() -> None:
    words = [FakeWord(0.0, 0.5, "a"), FakeWord(0.5, 1.0, "b")]

    assert [w["text"] for w in asr_words(words).words] == ["a", "b"]


def test_asr_words_names_the_word_for_a_non_finite_time() -> None:
    words = [FakeWord(0.0, 0.5, "a"), FakeWord(math.nan, 1.0, "b")]

    with pytest.raises(ValueError, match="word 2"):
        asr_words(words)
