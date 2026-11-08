from collections.abc import Iterable

from lirisync_worker.anchor import (
    AnchoredLine,
    AnchorOptions,
    Segment,
    Word,
    anchor_lines,
    auto_pairing,
    default_threshold,
    similarity,
    split_by_breath,
)
from lirisync_worker.match_text import MatchForms, Token


def read_as_written(text: str) -> Iterable[Token]:
    """A reader whose reading is the text itself, so both forms agree."""
    return [Token(surface=text, reading=text)]


def word(start: int, end: int, text: str = "x") -> Word:
    return Word(start=start, end=end, text=text)


def segment(start: int, end: int, text: str, words: tuple[Word, ...] = ()) -> Segment:
    return Segment(start=start, end=end, text=text, words=words)


def starts(lines: list[AnchoredLine]) -> list[int | None]:
    return [line.start for line in lines]


# similarity


def test_identical_forms_are_fully_similar() -> None:
    forms = MatchForms(surface="かぜ", reading="かぜ")
    assert similarity(forms, forms) == 1.0


def test_similarity_takes_the_better_of_surface_and_reading() -> None:
    lyric = MatchForms(surface="運命", reading="さだめ")
    heard = MatchForms(surface="定め", reading="さだめ")
    assert similarity(lyric, heard) == 1.0


# default_threshold


def test_japanese_lyrics_get_the_low_threshold() -> None:
    assert default_threshold(["かぜがふく", "そらをとぶ"]) == 0.25


def test_latin_lyrics_get_the_high_threshold() -> None:
    assert default_threshold(["amazing grace", "how sweet the sound"]) == 0.5


# auto_pairing


def test_pairing_rounds_lines_per_segment() -> None:
    assert auto_pairing(lines=40, segments=20) == 2


def test_pairing_is_at_least_one() -> None:
    assert auto_pairing(lines=76, segments=64) == 1


def test_pairing_is_capped_at_three() -> None:
    assert auto_pairing(lines=50, segments=5) == 3


def test_pairing_without_segments_is_one() -> None:
    assert auto_pairing(lines=10, segments=0) == 1


# split_by_breath


def test_split_cuts_at_the_longest_gap_near_the_target() -> None:
    words = (word(0, 100), word(150, 250), word(900, 1000), word(1050, 1150))
    groups = split_by_breath(words, [2, 2])
    assert [len(group) for group in groups] == [2, 2]


def test_split_prefers_a_breath_over_the_exact_character_ratio() -> None:
    words = (word(0, 100), word(800, 900), word(950, 1050), word(1100, 1200))
    groups = split_by_breath(words, [2, 2])
    assert [len(group) for group in groups] == [1, 3]


def test_split_of_one_line_keeps_every_word() -> None:
    words = (word(0, 100), word(200, 300))
    assert split_by_breath(words, [5]) == [list(words)]


def test_split_with_fewer_words_than_lines_leaves_empty_groups() -> None:
    words = (word(0, 100),)
    assert split_by_breath(words, [1, 1]) == [list(words), []]


# anchor_lines


def test_each_line_takes_the_span_of_its_segment() -> None:
    segments = [segment(1000, 2000, "かぜがふく"), segment(3000, 4000, "そらをとぶ")]
    result = anchor_lines(
        ["かぜがふく", "そらをとぶ"], segments, read_as_written, AnchorOptions(pairing=1)
    )
    assert starts(result) == [1000, 3000]


def test_a_matched_line_ends_with_its_segment() -> None:
    segments = [segment(1000, 2000, "かぜがふく")]
    result = anchor_lines(["かぜがふく"], segments, read_as_written, AnchorOptions(pairing=1))
    assert result[0].end == 2000


def test_a_line_below_the_threshold_is_unmatched_without_a_time() -> None:
    segments = [segment(1000, 2000, "かぜがふく")]
    result = anchor_lines(["ほしをみる"], segments, read_as_written, AnchorOptions(pairing=1))
    assert (result[0].status, result[0].start) == ("unmatched", None)


def test_an_unmatched_line_does_not_consume_a_segment() -> None:
    segments = [segment(1000, 2000, "そらをとぶ")]
    result = anchor_lines(
        ["ほしをみる", "そらをとぶ"], segments, read_as_written, AnchorOptions(pairing=1)
    )
    assert starts(result) == [None, 1000]


def test_a_repeated_line_takes_the_repetitions_in_order() -> None:
    segments = [
        segment(1000, 2000, "かぜがふく"),
        segment(3000, 4000, "そらをとぶ"),
        segment(5000, 6000, "かぜがふく"),
    ]
    lyrics = ["かぜがふく", "そらをとぶ", "かぜがふく"]
    result = anchor_lines(lyrics, segments, read_as_written, AnchorOptions(pairing=1))
    assert starts(result) == [1000, 3000, 5000]


def test_a_match_beyond_the_window_is_not_taken() -> None:
    segments = [segment(i * 1000, i * 1000 + 500, f"ちがう{i}") for i in range(4)]
    segments.append(segment(9000, 9500, "かぜがふく"))
    result = anchor_lines(
        ["かぜがふく"], segments, read_as_written, AnchorOptions(pairing=1, window=4)
    )
    assert result[0].status == "unmatched"


def test_a_symbol_only_line_passes_through_without_a_time() -> None:
    segments = [segment(1000, 2000, "かぜがふく"), segment(3000, 4000, "そらをとぶ")]
    lyrics = ["かぜがふく", "☆☆☆", "そらをとぶ"]
    result = anchor_lines(lyrics, segments, read_as_written, AnchorOptions(pairing=1))
    assert [line.status for line in result] == ["anchor", "not_sung", "anchor"]


def test_a_blank_line_is_not_sung() -> None:
    result = anchor_lines([""], [], read_as_written)
    assert result[0].status == "not_sung"


def test_two_lines_in_one_segment_are_split_at_the_breath() -> None:
    words = (
        word(1000, 1400, "かぜが"),
        word(1450, 1800, "ふく"),
        word(2600, 3000, "そらを"),
        word(3050, 3400, "とぶ"),
    )
    segments = [segment(1000, 3400, "かぜがふくそらをとぶ", words)]
    result = anchor_lines(
        ["かぜがふく", "そらをとぶ"], segments, read_as_written, AnchorOptions(pairing=2)
    )
    assert starts(result) == [1000, 2600]


def test_split_lines_without_word_timings_share_the_segment_span() -> None:
    segments = [segment(1000, 3400, "かぜがふくそらをとぶ")]
    result = anchor_lines(
        ["かぜがふく", "そらをとぶ"], segments, read_as_written, AnchorOptions(pairing=2)
    )
    assert starts(result) == [1000, 1000]


def test_every_lyric_line_gets_one_result() -> None:
    lyrics = ["かぜがふく", "", "☆", "ほしをみる"]
    result = anchor_lines(lyrics, [segment(0, 1000, "かぜがふく")], read_as_written)
    assert len(result) == len(lyrics)


def test_pairing_defaults_to_the_lines_per_segment() -> None:
    words = (word(1000, 1500), word(2500, 3000))
    segments = [segment(1000, 3000, "かぜがふくそらをとぶ", words)]
    result = anchor_lines(["かぜがふく", "そらをとぶ"], segments, read_as_written)
    assert starts(result) == [1000, 2500]
