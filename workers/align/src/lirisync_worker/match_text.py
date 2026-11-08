"""Turn display text (lyrics or ASR output) into text for fuzzy matching.

Display text is never changed; only these derived forms are compared. Two forms
are produced because ASR writes kanji: the surface form catches lines where the
ASR picked the same kanji, and the reading form catches lines where it picked
different kanji or kana for the same sound (and ateji such as 運命 sung as
さだめ, once a reading is supplied).
"""

import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class Token:
    surface: str
    reading: str


type Reader = Callable[[str], Iterable[Token]]


@dataclass(frozen=True)
class MatchForms:
    surface: str
    reading: str


_KANJI_MARK = "々"
_KANA_MARKS = {"ゝ": False, "ゞ": True, "ヽ": False, "ヾ": True}  # mark -> voiced
_DAKUTEN = "\u3099"  # combining voiced sound mark, not the spacing U+309B
_HANDAKUTEN = "\u309a"  # combining semi-voiced sound mark

# Unicode general categories dropped before matching: punctuation, symbols
# (☆ ♪ ♡ and most emoji), separators, control/format (ZWJ), enclosing marks
# (keycap). The long vowel mark ー is Lm and survives here; fold_kana drops it.
_IGNORED_CATEGORY_PREFIXES = ("P", "S", "Z", "C")
_IGNORED_CATEGORIES = frozenset({"Me"})


_VARIATION_SELECTORS = (range(0xFE00, 0xFE0F + 1), range(0xE0100, 0xE01EF + 1))


def _is_variation_selector(ch: str) -> bool:
    return any(ord(ch) in block for block in _VARIATION_SELECTORS)


def _unvoiced(ch: str) -> str:
    decomposed = unicodedata.normalize("NFD", ch)
    return unicodedata.normalize("NFC", decomposed.replace(_DAKUTEN, "").replace(_HANDAKUTEN, ""))


def _voiced(ch: str) -> str:
    composed = unicodedata.normalize("NFC", _unvoiced(ch) + _DAKUTEN)
    return composed if len(composed) == 1 else _unvoiced(ch)


def expand_iteration_marks(text: str, *, kanji: bool) -> str:
    """Replace 々 (when `kanji`), ゝ ゞ ヽ ヾ with the character they repeat.

    々 is left alone for the reading path because the dictionary reads 時々 as
    ときどき but 時時 as じじ. ゝ is always expanded because the dictionary reads
    a lone ゝ as the particle の. A mark with nothing before it is dropped.
    """
    out: list[str] = []
    for ch in text:
        if ch == _KANJI_MARK and kanji:
            if out:
                out.append(out[-1])
            continue
        if ch in _KANA_MARKS:
            if out:
                previous = out[-1]
                out.append(_voiced(previous) if _KANA_MARKS[ch] else _unvoiced(previous))
            continue
        out.append(ch)
    return "".join(out)


def strip_ignored(text: str, ignored: frozenset[str]) -> str:
    """Drop punctuation, symbols, emoji, spaces and the user's extra characters."""
    return "".join(
        ch
        for ch in text
        if ch not in ignored
        and not _is_variation_selector(ch)
        and not unicodedata.category(ch).startswith(_IGNORED_CATEGORY_PREFIXES)
        and unicodedata.category(ch) not in _IGNORED_CATEGORIES
    )


_KATAKANA_START = 0x30A1  # ァ
_KATAKANA_END = 0x30F6  # ヶ
_KATAKANA_TO_HIRAGANA = 0x60
_SMALL_KANA = str.maketrans(
    {
        "ぁ": "あ",
        "ぃ": "い",
        "ぅ": "う",
        "ぇ": "え",
        "ぉ": "お",
        "ゃ": "や",
        "ゅ": "ゆ",
        "ょ": "よ",
        "ゎ": "わ",
        "ゕ": "か",
        "ゖ": "け",
        "っ": None,
        "ー": None,
        # Small katakana extensions (U+31F0..U+31FF) sit outside the katakana
        # block shifted above, so map them to full-size hiragana directly.
        "ㇰ": "く",
        "ㇱ": "し",
        "ㇲ": "す",
        "ㇳ": "と",
        "ㇴ": "ぬ",
        "ㇵ": "は",
        "ㇶ": "ひ",
        "ㇷ": "ふ",
        "ㇸ": "へ",
        "ㇹ": "ほ",
        "ㇺ": "む",
        "ㇻ": "ら",
        "ㇼ": "り",
        "ㇽ": "る",
        "ㇾ": "れ",
        "ㇿ": "ろ",
    }
)


def fold_kana(text: str) -> str:
    """Katakana to hiragana, small kana to full size, drop っ and ー.

    Sung vowels stretch and clip freely, so あぁー, ああ and あー should compare
    equal; folding both sides the same way is enough for a similarity score.
    """
    hiragana = "".join(
        chr(ord(ch) - _KATAKANA_TO_HIRAGANA) if _KATAKANA_START <= ord(ch) <= _KATAKANA_END else ch
        for ch in text
    )
    # NFC composes a mark left behind by the mapping (ㇷ + U+309A -> ぷ).
    return unicodedata.normalize("NFC", hiragana.translate(_SMALL_KANA))


def _fold(text: str) -> str:
    return fold_kana(strip_ignored(text.casefold(), frozenset()))


@cache
def _folded_ignored(ignored: frozenset[str]) -> frozenset[str]:
    """The user's extra characters, normalized the same way as the text.

    Comparing them only before folding would miss the folded text: ら would not
    remove ラ, and a full-width A (U+FF21) would not remove the a that NFKC and
    casefold produce.

    Each character is normalized on its own so that neighbours never compose
    (か next to ゛ would become が, in an order that varies per run). A character
    that expands to several (U+337B to 平成, ß to ss) is left out: the text is
    expanded the same way, so it could only remove those parts everywhere.
    """
    folded = (_fold(unicodedata.normalize("NFKC", ch)) for ch in ignored)
    return frozenset(f for f in folded if len(f) == 1)


def _finish(text: str, ignored: frozenset[str]) -> str:
    drop = _folded_ignored(ignored)
    return "".join(ch for ch in _fold(text) if ch not in drop)


def surface_form(text: str, ignored: frozenset[str]) -> str:
    """NFKC, expand all iteration marks, then fold. Kanji are kept as written."""
    normalized = unicodedata.normalize("NFKC", text)
    return _finish(expand_iteration_marks(normalized, kanji=True), ignored)


def reading_form(text: str, read: Reader, ignored: frozenset[str]) -> str:
    """Read each token as kana, then fold. See `reading_chars`, which this joins.

    Tokens whose surface folds to nothing are skipped: the dictionary gives
    spaces and ☆ the reading キゴウ ("symbol"), and an ignored character such
    as U+3007 (ideographic zero) its reading マル, which would otherwise leak
    into the text being matched. A token without a reading keeps its surface.
    """
    return "".join(ch for ch, _ in reading_chars([text], read, ignored))


def match_forms(text: str, read: Reader, ignored: frozenset[str]) -> MatchForms:
    return MatchForms(
        surface=surface_form(text, ignored), reading=reading_form(text, read, ignored)
    )


def is_symbol_only(text: str, ignored: frozenset[str]) -> bool:
    """True for lines such as ☆☆☆ that should pass through without timing."""
    return surface_form(text, ignored) == ""


def reading_chars(
    texts: Sequence[str], read: Reader, ignored: frozenset[str]
) -> list[tuple[str, int]]:
    """Folded reading characters of `texts` read as one, each tagged with the
    index of the text it came from.

    ASR words are short fragments: Whisper may split 運命 into 運 and 命, and
    命 read alone is いのち. Reading the joined text keeps the dictionary's
    context; a token that spans several texts hands out its reading in
    proportion to the characters each text contributed.
    """
    normalized = [
        expand_iteration_marks(unicodedata.normalize("NFKC", t), kanji=False) for t in texts
    ]
    joined = "".join(normalized)
    owner = [index for index, text in enumerate(normalized) for _ in text]
    out: list[tuple[str, int]] = []
    offset = 0
    for token in read(joined):
        # Check each token in place: a reader that normalized its surfaces
        # could keep the total length and still shift every owner silently.
        if not joined.startswith(token.surface, offset):
            raise ValueError("reader token surfaces do not cover the input text")
        span = owner[offset : offset + len(token.surface)]
        offset += len(token.surface)
        reading = _finish(token.reading or token.surface, ignored)
        if not span or not _finish(token.surface, ignored):
            continue
        out.extend((ch, span[k * len(span) // len(reading)]) for k, ch in enumerate(reading))
    if offset != len(joined):
        raise ValueError("reader token surfaces do not cover the input text")
    return out
