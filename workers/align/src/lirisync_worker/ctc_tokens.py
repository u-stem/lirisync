"""Text to CTC token ids for the character model.

The model's vocabulary has one-character tokens (kanji, kana, small kana, っ, ー,
lower-case a-z, digits, a few marks) and longer ones such as "▁あ" and "10". Only
the one-character tokens are used here, so a line is spelled character by
character and every id stands for exactly one character of the text.

Two spellings of a lyric line can be forced: `surface_text` keeps the kanji as
written, and `kana_text` uses the dictionary reading as hiragana. Both drop what
is not sung (punctuation, symbols, spaces, the user's ignored characters) with
the same rules as the first matching stage in `match_text`.
"""

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from lirisync_worker.match_text import (
    Reader,
    expand_iteration_marks,
    finish,
    katakana_to_hiragana,
    reading_chars,
    strip_ignored,
)

# Kana that the model has no token for, and what they are sung as. Katakana are
# shifted to hiragana first, so ヮ ヰ ヱ ヵ ヶ arrive here as ゎ ゐ ゑ ゕ ゖ. ゔ goes
# the other way because ヴ (but not ゔ) is a token.
_NO_TOKEN_KANA = str.maketrans(
    {"ゎ": "わ", "ゐ": "い", "ゑ": "え", "ゕ": "か", "ゖ": "け", "ゔ": "ヴ"}
)


@dataclass(frozen=True)
class Encoded:
    ids: tuple[int, ...]
    chars: str  # the character of each id, in order
    skipped: str  # characters with no token, in the order they appeared


class CharVocab:
    """The one-character tokens of a vocabulary (token string to id)."""

    def __init__(self, vocab: Mapping[str, int]) -> None:
        self._ids = {token: token_id for token, token_id in vocab.items() if len(token) == 1}

    def __len__(self) -> int:
        return len(self._ids)

    def encode(self, text: str) -> Encoded:
        """Spell `text` as token ids; characters without a token are reported, not guessed."""
        ids: list[int] = []
        chars: list[str] = []
        skipped: list[str] = []
        for ch in text:
            token_id = self._ids.get(ch)
            if token_id is None:
                skipped.append(ch)
            else:
                ids.append(token_id)
                chars.append(ch)
        return Encoded(ids=tuple(ids), chars="".join(chars), skipped="".join(skipped))


def _surface_fold(text: str) -> str:
    return strip_ignored(text.casefold(), frozenset())


def _kana_fold(text: str) -> str:
    hiragana = katakana_to_hiragana(strip_ignored(text.casefold(), frozenset()))
    return hiragana.translate(_NO_TOKEN_KANA)


def surface_text(line: str, ignored: frozenset[str]) -> str:
    """The line as written: NFKC and casefolded, kanji kept, nothing sung dropped.

    Unlike `match_text.surface_form`, kana are not folded: the model has tokens
    for small kana, っ, ー and katakana, and dropping them would shorten the
    spelling the singer actually produced.

    々 is kept as it is, because the vocabulary has a token for it; the kana
    marks ゝ ゞ ヽ ヾ have none, so they are expanded to the kana they repeat.
    """
    normalized = unicodedata.normalize("NFKC", line)
    return finish(expand_iteration_marks(normalized, kanji=False), ignored, _surface_fold)


def kana_text(line: str, read: Reader, ignored: frozenset[str]) -> str:
    """The line's reading as hiragana, keeping the small kana, っ and ー.

    A token without a reading keeps its surface. Tokens that are only symbols or
    ignored characters are skipped, so ☆ is not read as キゴウ (see
    `match_text.reading_chars`). Kana without a token are replaced; see
    `_NO_TOKEN_KANA`.
    """
    return "".join(ch for ch, _ in reading_chars([line], read, ignored, _kana_fold))
