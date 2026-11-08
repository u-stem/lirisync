"""Kana readings from SudachiPy with the bundled core dictionary."""

from collections.abc import Iterable

from sudachipy import Dictionary, SplitMode

from lirisync_worker.match_text import Token


class SudachiReader:
    """A `Reader` backed by SudachiPy.

    Split mode C (the longest units) is used so that compounds keep their
    dictionary reading instead of being read one part at a time. Loading the
    dictionary takes about 0.1 s, so create one reader and reuse it.
    """

    def __init__(self) -> None:
        self._tokenizer = Dictionary(dict="core").tokenizer(mode=SplitMode.C)

    def __call__(self, text: str) -> Iterable[Token]:
        return [
            Token(surface=morpheme.surface(), reading=morpheme.reading_form())
            for morpheme in self._tokenizer.tokenize(text)
        ]
