"""Kana readings from SudachiPy with the bundled core dictionary."""

from collections.abc import Iterable, Sequence

from sudachipy import Dictionary, SplitMode

from lirisync_worker.match_text import Token

# Particles after which a lone 何 is read なに and never なん. Elsewhere both
# occur: 何で (なにで "with what", なんで "why"), 何と, 何の, and in lyrics 何か
# (なんか), 何も (なんも), 何にも (なんにも); those keep the dictionary reading.
_NANI_BEFORE = ("ヲ", "ガ")


def read_nani(tokens: Sequence[Token]) -> list[Token]:
    """Read a lone 何 as ナニ before を or が; the core dictionary reads it ナン.

    Only the readings that cannot be なん are changed. Where both are possible
    the text cannot tell which the singer chose, so the dictionary's reading
    stays. Compounds such as 何度 or 何者 come as one token with their own
    reading and are left alone.
    """
    fixed: list[Token] = []
    for index, token in enumerate(tokens):
        following = tokens[index + 1].reading if index + 1 < len(tokens) else ""
        if token.surface == "何" and token.reading == "ナン" and following.startswith(_NANI_BEFORE):
            fixed.append(Token(surface=token.surface, reading="ナニ"))
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
