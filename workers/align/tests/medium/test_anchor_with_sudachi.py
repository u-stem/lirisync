import pytest

from lirisync_worker.anchor import AnchorOptions, Segment, anchor_lines
from lirisync_worker.sudachi_reader import SudachiReader


@pytest.fixture(scope="module")
def reader() -> SudachiReader:
    return SudachiReader()


def test_a_line_matches_asr_that_wrote_it_in_kana(reader: SudachiReader) -> None:
    segments = [Segment(start=1200, end=3400, text="きみをあいしてる")]
    result = anchor_lines(["君を愛してる"], segments, reader, AnchorOptions(pairing=1))
    assert result[0].start == 1200


def test_english_in_a_line_matches_katakana_asr(reader: SudachiReader) -> None:
    segments = [Segment(start=500, end=2000, text="アイラブユー")]
    result = anchor_lines(["I love you"], segments, reader, AnchorOptions(pairing=1))
    assert result[0].status == "anchor"
