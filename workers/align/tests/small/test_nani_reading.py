import pytest

from lirisync_worker.match_text import Token
from lirisync_worker.sudachi_reader import read_nani


def _readings(tokens: list[Token]) -> list[str]:
    return [token.reading for token in read_nani(tokens)]


@pytest.mark.parametrize("particle", ["ヲ", "ガ"])
def test_nani_before_wo_and_ga(particle: str) -> None:
    tokens = [Token("何", "ナン"), Token("x", particle)]
    assert _readings(tokens)[0] == "ナニ"


# Both readings occur here (何で: by what / why; 何か: なにか / なんか), so the
# dictionary's reading stays.
@pytest.mark.parametrize("following", ["デ", "ト", "ノ", "カ", "モ", "ニ", "ダ"])  # noqa: RUF001
def test_keeps_the_dictionary_reading_where_both_occur(following: str) -> None:
    tokens = [Token("何", "ナン"), Token("x", following)]
    assert _readings(tokens)[0] == "ナン"


def test_keeps_the_dictionary_reading_at_the_end() -> None:
    assert _readings([Token("それ", "ソレ"), Token("何", "ナン")]) == ["ソレ", "ナン"]


def test_leaves_compounds_alone() -> None:
    assert _readings([Token("何度", "ナンド"), Token("を", "ヲ")]) == ["ナンド", "ヲ"]


def test_leaves_other_tokens_alone() -> None:
    assert _readings([Token("君", "キミ"), Token("を", "ヲ")]) == ["キミ", "ヲ"]
