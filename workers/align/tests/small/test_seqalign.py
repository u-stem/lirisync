from lirisync_worker.seqalign import align


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
