from collections.abc import Iterable

import pytest

from lirisync_worker.ctc_tokens import CharVocab, kana_text, surface_text
from lirisync_worker.match_text import Token

NONE: frozenset[str] = frozenset()


class FakeReader:
    """Reads a whole line as one token if it is in `lines`, else one token per character."""

    def __init__(self, readings: dict[str, str], lines: dict[str, list[Token]] | None = None):
        self._readings = readings
        self._lines = lines or {}

    def __call__(self, text: str) -> Iterable[Token]:
        if text in self._lines:
            return self._lines[text]
        return [Token(surface=ch, reading=self._readings.get(ch, "")) for ch in text]


# CharVocab.encode


def test_encode_maps_characters_to_their_ids() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5, "い": 7})

    assert vocab.encode("あい").ids == (5, 7)


def test_encode_returns_the_characters_the_ids_stand_for() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5, "い": 7})

    assert vocab.encode("あい").chars == "あい"


def test_encode_repeats_the_id_of_a_repeated_character() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5})

    assert vocab.encode("ああ").ids == (5, 5)


def test_encode_reports_characters_missing_from_the_vocabulary() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5})

    assert vocab.encode("あ🙂あ").skipped == "🙂"


def test_encode_leaves_skipped_characters_out_of_ids_and_chars_alike() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5, "い": 7})

    assert vocab.encode("あ🙂い").chars == "あい"


def test_encode_of_nothing_is_empty() -> None:
    assert CharVocab({"<unk>": 0, "あ": 5}).encode("").ids == ()


def test_only_one_character_tokens_are_used() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5, "▁あ": 9, "10": 11})

    assert vocab.encode("あ").ids == (5,)


def test_a_multi_character_token_is_not_matched_as_a_unit() -> None:
    vocab = CharVocab({"<unk>": 0, "▁あ": 9})

    assert vocab.encode("あ").skipped == "あ"


def test_a_vocabulary_of_one_character_tokens_reports_their_count() -> None:
    vocab = CharVocab({"<unk>": 0, "あ": 5, "い": 7, "▁あ": 9})

    assert len(vocab) == 2


# surface_text


def test_surface_text_keeps_kanji_as_written() -> None:
    assert surface_text("君を", NONE) == "君を"


def test_surface_text_applies_nfkc_and_casefold() -> None:
    assert surface_text("ＡＢｃ", NONE) == "abc"


def test_surface_text_keeps_the_kanji_iteration_mark_because_the_vocabulary_has_it() -> None:
    assert surface_text("人々", NONE) == "人々"


def test_surface_text_expands_the_kana_iteration_mark() -> None:
    assert surface_text("かゝ", NONE) == "かか"


def test_surface_text_expands_the_voiced_kana_iteration_mark() -> None:
    assert surface_text("すゞ", NONE) == "すず"


def test_surface_text_drops_punctuation_symbols_and_spaces() -> None:
    assert surface_text("あ、い ☆う♪!", NONE) == "あいう"


def test_surface_text_drops_the_users_ignored_characters() -> None:
    assert surface_text("あxい", frozenset("x")) == "あい"


def test_surface_text_drops_an_ignored_character_in_its_folded_form() -> None:
    assert surface_text("abc", frozenset("Ｂ")) == "ac"


def test_surface_text_keeps_the_long_vowel_mark() -> None:
    assert surface_text("ラーメン", NONE) == "ラーメン"


def test_surface_text_keeps_small_kana() -> None:
    assert surface_text("きっとゃ", NONE) == "きっとゃ"


def test_surface_text_keeps_katakana_as_written() -> None:
    assert surface_text("カナ", NONE) == "カナ"


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("ヮ", "ワ"),
        ("ヰ", "イ"),
        ("ヲ", "オ"),
        ("ヵ", "カ"),
        ("ヷ", "ヴァ"),
        ("ヸ", "ヴィ"),
        ("ヹ", "ヴェ"),
        ("ヺ", "ヴォ"),
        ("ㇰ", "ク"),
        ("ㇷ", "フ"),
        ("ㇿ", "ロ"),
        ("ㇷ゚", "プ"),
        ("ゎ", "わ"),
        ("ゐ", "い"),
        ("ゑ", "え"),
        ("ゕ", "か"),
        ("ゖ", "け"),
        ("ゔ", "ヴ"),
    ],
)
def test_surface_text_replaces_kana_the_model_has_no_token_for(written: str, expected: str) -> None:
    assert surface_text(written, NONE) == expected


# kana_text


def test_kana_text_uses_the_reading_as_hiragana() -> None:
    assert kana_text("君", FakeReader({"君": "キミ"}), NONE) == "きみ"


def test_kana_text_keeps_the_small_tsu() -> None:
    assert kana_text("切", FakeReader({"切": "キッ"}), NONE) == "きっ"


def test_kana_text_keeps_the_long_vowel_mark() -> None:
    assert kana_text("珈琲", FakeReader({}, {"珈琲": [Token("珈琲", "コーヒー")]}), NONE) == (
        "こーひー"
    )


def test_kana_text_keeps_small_kana() -> None:
    assert kana_text("写", FakeReader({"写": "シャ"}), NONE) == "しゃ"


def test_kana_text_uses_the_surface_of_a_token_without_a_reading() -> None:
    assert kana_text("abc", FakeReader({}), NONE) == "abc"


def test_kana_text_casefolds_a_surface_used_as_its_own_reading() -> None:
    assert kana_text("ＡＢ", FakeReader({}), NONE) == "ab"


def test_kana_text_does_not_read_a_symbol_as_its_dictionary_reading() -> None:
    reader = FakeReader({"☆": "キゴウ", "あ": "ア"})

    assert kana_text("☆あ", reader, NONE) == "あ"


def test_kana_text_drops_the_reading_of_an_ignored_character() -> None:
    reader = FakeReader({"〇": "マル", "あ": "ア"})

    assert kana_text("〇あ", reader, frozenset("〇")) == "あ"


def test_kana_text_drops_the_users_ignored_character_in_its_hiragana_form() -> None:
    assert kana_text("ラ", FakeReader({}), frozenset("ら")) == ""


def test_kana_text_drops_spaces_between_tokens() -> None:
    assert kana_text("あ い", FakeReader({"あ": "ア", "い": "イ"}), NONE) == "あい"


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        ("ゎ", "わ"),
        ("ゐ", "い"),
        ("ゑ", "え"),
        ("ゕ", "か"),
        ("ゖ", "け"),
        ("ヮ", "わ"),
        ("ヰ", "い"),
        ("ヱ", "え"),
        ("ヵ", "か"),
        ("ヶ", "け"),
        ("ヴ", "ヴ"),
        ("ヷ", "ヴぁ"),
        ("ヸ", "ヴぃ"),
        ("ヹ", "ヴぇ"),
        ("ヺ", "ヴぉ"),
        ("ㇰ", "く"),
        ("ㇷ", "ふ"),
        ("ㇿ", "ろ"),
        ("ㇷ゚", "ぷ"),
    ],
)
def test_kana_text_replaces_kana_the_model_has_no_token_for(reading: str, expected: str) -> None:
    assert kana_text("x", FakeReader({"x": reading}), NONE) == expected
