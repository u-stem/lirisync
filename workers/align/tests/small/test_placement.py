from collections.abc import Iterable

from lirisync_worker.match_text import Token
from lirisync_worker.placement import PlacedLine, PlacementOptions, Word, place_lines


def read_by_character(text: str) -> Iterable[Token]:
    return [Token(surface=ch, reading=ch) for ch in text]


def sung(text: str, start: int, step: int = 100) -> list[Word]:
    """One ASR word per character, `step` ms apart, each `step - 20` ms long."""
    return [
        Word(start=start + k * step, end=start + k * step + step - 20, text=ch)
        for k, ch in enumerate(text)
    ]


def starts(lines: list[PlacedLine]) -> list[int | None]:
    return [line.start for line in lines]


def test_each_line_starts_at_its_first_aligned_word() -> None:
    words = sung("かぜがふく", 1000) + sung("そらをとぶ", 3000)
    result = place_lines(["かぜがふく", "そらをとぶ"], words, read_by_character)
    assert starts(result) == [1000, 3000]


def test_a_line_ends_with_its_last_aligned_word() -> None:
    words = sung("かぜがふく", 1000)
    result = place_lines(["かぜがふく"], words, read_by_character)
    assert result[0].end == 1480


def test_a_line_the_asr_did_not_hear_is_unmatched() -> None:
    words = sung("かぜがふく", 1000) + sung("そらをとぶ", 5000)
    lyrics = ["かぜがふく", "ほしをみる", "そらをとぶ"]
    result = place_lines(lyrics, words, read_by_character)
    assert [line.status for line in result] == ["anchor", "unmatched", "anchor"]


def test_an_unmatched_line_has_no_time() -> None:
    result = place_lines(["かぜがふく"], [], read_by_character)
    assert (result[0].start, result[0].end) == (None, None)


def test_a_misheard_line_keeps_its_place() -> None:
    words = sung("きみおあいしてる", 2000)
    result = place_lines(["きみをあいしてる"], words, read_by_character)
    assert result[0].start == 2000


def test_the_match_ratio_counts_exact_characters() -> None:
    words = sung("きみおあいしてる", 2000)
    result = place_lines(["きみをあいしてる"], words, read_by_character)
    assert result[0].match_ratio == 7 / 8


def test_a_line_below_the_minimum_ratio_is_unmatched() -> None:
    words = sung("きみおあいしてる", 2000)
    options = PlacementOptions(min_match_ratio=0.9)
    result = place_lines(["きみをあいしてる"], words, read_by_character, options)
    assert result[0].status == "unmatched"


def test_symbol_only_and_blank_lines_are_not_sung() -> None:
    words = sung("かぜがふく", 1000)
    result = place_lines(["☆☆☆", "", "かぜがふく"], words, read_by_character)
    assert [line.status for line in result] == ["not_sung", "not_sung", "anchor"]


def test_a_repeated_line_takes_each_repetition_in_order() -> None:
    words = sung("かぜがふく", 1000) + sung("そらをとぶ", 3000) + sung("かぜがふく", 5000)
    lyrics = ["かぜがふく", "そらをとぶ", "かぜがふく"]
    result = place_lines(lyrics, words, read_by_character)
    assert starts(result) == [1000, 3000, 5000]


def test_a_missed_repetition_fixed_by_order_is_not_ambiguous() -> None:
    words = sung("かぜがふく", 1000) + sung("そらをとぶ", 3000)
    lyrics = ["かぜがふく", "そらをとぶ", "かぜがふく"]
    result = place_lines(lyrics, words, read_by_character)
    assert [line.ambiguous for line in result] == [False, False, False]


def test_a_missed_back_to_back_repetition_is_ambiguous() -> None:
    words = sung("かぜがふく", 1000)
    result = place_lines(["かぜがふく", "かぜがふく"], words, read_by_character)
    assert [line.ambiguous for line in result] == [True, True]


def test_a_missed_repeated_block_marks_the_whole_block_ambiguous() -> None:
    words = sung("かぜがふく", 1000) + sung("そらをとぶ", 3000)
    lyrics = ["かぜがふく", "そらをとぶ", "かぜがふく", "そらをとぶ"]
    result = place_lines(lyrics, words, read_by_character)
    assert [line.ambiguous for line in result] == [True, True, True, True]


def test_every_lyric_line_gets_one_result() -> None:
    lyrics = ["かぜがふく", "", "☆", "ほしをみる"]
    result = place_lines(lyrics, sung("かぜがふく", 0), read_by_character)
    assert len(result) == len(lyrics)
