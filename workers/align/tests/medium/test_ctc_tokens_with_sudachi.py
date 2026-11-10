import pytest

from lirisync_worker.ctc_tokens import kana_text
from lirisync_worker.sudachi_reader import SudachiReader

NONE: frozenset[str] = frozenset()


@pytest.fixture(scope="module")
def reader() -> SudachiReader:
    return SudachiReader()


def test_kanji_iteration_mark_gets_the_dictionary_reading(reader: SudachiReader) -> None:
    assert kana_text("時々", reader, NONE) == "ときどき"


def test_the_long_vowel_mark_of_a_loanword_is_kept(reader: SudachiReader) -> None:
    assert kana_text("ラーメン", reader, NONE) == "らーめん"


def test_the_small_tsu_of_a_reading_is_kept(reader: SudachiReader) -> None:
    assert kana_text("ずっと", reader, NONE) == "ずっと"


def test_spaces_and_stars_do_not_read_as_kigou(reader: SudachiReader) -> None:
    assert kana_text("あぁー ☆", reader, NONE) == "あぁー"


def test_full_width_digits_are_read(reader: SudachiReader) -> None:
    assert kana_text("２人で", reader, NONE) == "ふたりで"
