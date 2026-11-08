from collections.abc import Iterable

from lirisync_worker.match_text import (
    Token,
    expand_iteration_marks,
    fold_kana,
    is_symbol_only,
    match_forms,
    reading_form,
    strip_ignored,
    surface_form,
)


class FakeReader:
    """Splits on single characters unless a whole surface is in `readings`."""

    def __init__(self, readings: dict[str, str]) -> None:
        self._readings = readings

    def __call__(self, text: str) -> Iterable[Token]:
        if text in self._readings:
            return [Token(surface=text, reading=self._readings[text])]
        return [Token(surface=ch, reading=self._readings.get(ch, ch)) for ch in text]


# expand_iteration_marks


def test_kanji_iteration_mark_repeats_the_previous_kanji() -> None:
    assert expand_iteration_marks("人々", kanji=True) == "人人"


def test_kanji_iteration_mark_is_kept_when_kanji_expansion_is_off() -> None:
    assert expand_iteration_marks("時々", kanji=False) == "時々"


def test_hiragana_iteration_mark_repeats_the_previous_kana() -> None:
    assert expand_iteration_marks("こゝろ", kanji=False) == "こころ"


def test_voiced_hiragana_iteration_mark_adds_dakuten() -> None:
    assert expand_iteration_marks("いすゞ", kanji=False) == "いすず"


def test_unvoiced_iteration_mark_after_a_voiced_kana_drops_dakuten() -> None:
    assert expand_iteration_marks("ぶゝ", kanji=False) == "ぶふ"


def test_katakana_iteration_mark_repeats_the_previous_kana() -> None:
    assert expand_iteration_marks("ココヽ", kanji=False) == "コココ"


def test_iteration_mark_at_the_start_is_dropped() -> None:
    assert expand_iteration_marks("々ゝ", kanji=True) == ""


# strip_ignored


def test_symbols_and_emoji_are_stripped() -> None:
    assert strip_ignored("あ☆い♪う♡え😀お", frozenset()) == "あいうえお"


def test_punctuation_and_spaces_are_stripped() -> None:
    assert strip_ignored("a, b!「c」〜d", frozenset()) == "abcd"


def test_emoji_modifiers_and_joiners_are_stripped() -> None:
    assert (
        strip_ignored(
            "\U0001f44d\U0001f3fd\U0001f468\u200d\U0001f469\u2764\ufe0f1\u20e3", frozenset()
        )
        == "1"
    )


def test_long_vowel_mark_survives_stripping() -> None:
    assert strip_ignored("あー", frozenset()) == "あー"


def test_extra_ignored_characters_are_stripped() -> None:
    assert strip_ignored("ラララ〇", frozenset({"〇"})) == "ラララ"


# fold_kana


def test_katakana_becomes_hiragana() -> None:
    assert fold_kana("カタカナヴ") == "かたかなゔ"


def test_small_kana_become_full_size() -> None:
    assert fold_kana("ぁぃぅぇぉゃゅょゎ") == "あいうえおやゆよわ"


def test_small_tsu_is_absorbed() -> None:
    assert fold_kana("きって") == "きて"


def test_small_katakana_extensions_become_hiragana() -> None:
    assert fold_kana("ㇰㇱㇺ") == "くしむ"


def test_combining_handakuten_is_composed() -> None:
    assert fold_kana("ㇷ\u309a") == "ぷ"


def test_long_vowel_mark_is_dropped() -> None:
    assert fold_kana("あぁー") == "ああ"


# surface_form


def test_surface_form_unifies_width_and_case() -> None:
    assert surface_form("ＬＯＶＥ ｶﾀｶﾅ", frozenset()) == "loveかたかな"


def test_surface_form_keeps_kanji() -> None:
    assert surface_form("運命（さだめ）", frozenset()) == "運命さだめ"


def test_surface_form_expands_kanji_iteration_marks() -> None:
    assert surface_form("時々", frozenset()) == surface_form("時時", frozenset())


# reading_form


def test_reading_form_uses_token_readings() -> None:
    reader = FakeReader({"運命": "ウンメイ"})
    assert reading_form("運命", reader, frozenset()) == "うんめい"


def test_reading_form_skips_symbol_tokens_with_spurious_readings() -> None:
    reader = FakeReader({" ": "キゴウ", "☆": "キゴウ"})
    assert reading_form("あ ☆い", reader, frozenset()) == "あい"


def test_reading_form_strips_symbols_inside_readings() -> None:
    reader = FakeReader({"4.5": "ヨン．ゴ"})
    assert reading_form("4.5", reader, frozenset()) == "よんご"


def test_reading_form_falls_back_to_the_surface_without_a_reading() -> None:
    reader = FakeReader({"x": ""})
    assert reading_form("x", reader, frozenset()) == "x"


def test_reading_form_leaves_kanji_iteration_marks_to_the_reader() -> None:
    reader = FakeReader({"時々": "トキドキ"})
    assert reading_form("時々", reader, frozenset()) == "ときどき"


def test_reading_form_expands_kana_iteration_marks_before_reading() -> None:
    reader = FakeReader({"こころ": "ココロ"})
    assert reading_form("こゝろ", reader, frozenset()) == "こころ"


def test_ignored_hiragana_also_drops_katakana_after_folding() -> None:
    reader = FakeReader({"ラララ": "ラララ"})
    assert reading_form("ラララ", reader, frozenset({"ら"})) == ""


def test_ignored_character_drops_the_reading_of_its_token() -> None:
    reader = FakeReader({"〇": "マル"})
    assert reading_form("あ〇", reader, frozenset({"〇"})) == "あ"


def test_ignored_full_width_letter_matches_its_folded_form() -> None:
    assert surface_form("abc", frozenset({"Ａ"})) == "bc"


def test_ignored_character_expanding_to_several_does_not_remove_them() -> None:
    assert surface_form("平成", frozenset({"\u337b"})) == "平成"


def test_ignored_characters_are_not_composed_with_each_other() -> None:
    assert surface_form("がか", frozenset({"か", "\u309b"})) == "が"


# match_forms / is_symbol_only


def test_match_forms_returns_both_forms() -> None:
    forms = match_forms("君", FakeReader({"君": "キミ"}), frozenset())
    assert (forms.surface, forms.reading) == ("君", "きみ")


def test_a_line_of_only_symbols_is_symbol_only() -> None:
    assert is_symbol_only("☆☆☆ ♪", frozenset()) is True


def test_a_line_with_kana_is_not_symbol_only() -> None:
    assert is_symbol_only("あぁー☆", frozenset()) is False


def test_a_line_of_only_long_vowel_marks_is_symbol_only() -> None:
    assert is_symbol_only("ーー", frozenset()) is True
