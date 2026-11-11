"""Kana readings from SudachiPy with the bundled core dictionary."""

from collections.abc import Iterable, Sequence

from sudachipy import Dictionary, SplitMode

from lirisync_worker.match_text import Token

# A lone 何 is read なん before a sound of the t, d or n rows (何だ, 何で, 何と,
# 何の, 何なの) and なに otherwise (何を, 何が, 何も, 何か, a line-final 何).
_NAN_BEFORE = frozenset("タダチヂツヅテデトドナヌネノ")


def read_nani(tokens: Sequence[Token]) -> list[Token]:
    """Fix the reading of a lone 何, which the core dictionary always reads ナン.

    Compounds such as 何度 or 何者 come as one token with their own reading and
    are left alone. The rule follows standard speech; a singer who says なんか
    for 何か is not covered.
    """
    fixed: list[Token] = []
    for index, token in enumerate(tokens):
        if token.surface == "何" and token.reading == "ナン":
            following = tokens[index + 1].reading if index + 1 < len(tokens) else ""
            reading = "ナン" if following[:1] in _NAN_BEFORE and following else "ナニ"
            fixed.append(Token(surface=token.surface, reading=reading))
        else:
            fixed.append(token)
    return fixed


class SudachiReader:
    """A `Reader` backed by SudachiPy.

    Split mode C (the longest units) is used so that compounds keep their
    dictionary reading instead of being read one part at a time. Loading the
    dictionary takes about 0.1 s, so create one reader and reuse it.
    """

    def __init__(self) -> None:
        self._tokenizer = Dictionary(dict="core").tokenizer(mode=SplitMode.C)

    def __call__(self, text: str) -> Iterable[Token]:
        return read_nani(
            [
                Token(surface=morpheme.surface(), reading=morpheme.reading_form())
                for morpheme in self._tokenizer.tokenize(text)
            ]
        )
