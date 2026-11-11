import pytest

from lirisync_worker.match_text import reading_form
from lirisync_worker.sudachi_reader import SudachiReader


@pytest.fixture(scope="module")
def reader() -> SudachiReader:
    return SudachiReader()


def test_kanji_iteration_mark_gets_the_dictionary_reading(reader: SudachiReader) -> None:
    assert reading_form("時々", reader, frozenset()) == "ときどき"


def test_english_words_get_katakana_readings(reader: SudachiReader) -> None:
    assert reading_form("I love you 君を", reader, frozenset()) == "あいらぶゆきみを"


def test_spaces_and_stars_do_not_read_as_kigou(reader: SudachiReader) -> None:
    assert reading_form("あぁー ☆", reader, frozenset()) == "ああ"


def test_full_width_digits_are_read(reader: SudachiReader) -> None:
    assert reading_form("２人で", reader, frozenset()) == "ふたりで"


@pytest.mark.parametrize(
    ("text", "reading"),
    # The match form folds small kana, so っ is gone from やっても.
    [("何をやっても", "なにをやても"), ("何が", "なにが"), ("何でも", "なんでも")],
)
def test_reads_a_lone_nani_before_wo_and_ga_only(
    reader: SudachiReader, text: str, reading: str
) -> None:
    assert reading_form(text, reader, frozenset()) == reading
