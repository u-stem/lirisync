import pytest

from lirisync_worker.match_text import reading_chars
from lirisync_worker.placement import Word, place_lines
from lirisync_worker.sudachi_reader import SudachiReader


@pytest.fixture(scope="module")
def reader() -> SudachiReader:
    return SudachiReader()


def test_split_asr_words_are_read_in_context(reader: SudachiReader) -> None:
    result = "".join(ch for ch, _ in reading_chars(["運", "命"], reader, frozenset()))
    assert result == "うんめい"


def test_a_kanji_line_is_placed_on_kana_asr_words(reader: SudachiReader) -> None:
    words = [
        Word(start=1200, end=1500, text="きみを"),
        Word(start=1500, end=2400, text="あいしてる"),
    ]
    result = place_lines(["君を愛してる"], words, reader)
    assert result[0].start == 1200
