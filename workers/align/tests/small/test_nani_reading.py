import pytest

from lirisync_worker.match_text import Token
from lirisync_worker.sudachi_reader import read_nani


def _readings(tokens: list[Token]) -> list[str]:
    return [token.reading for token in read_nani(tokens)]


@pytest.mark.parametrize("particle", ["ヲ", "ガ", "モ", "カ", "ニ", "ハ", "ヨリ", "カラ"])
def test_nani_before_a_particle_that_does_not_start_with_t_d_or_n(particle: str) -> None:
    tokens = [Token("何", "ナン"), Token("x", particle)]
    assert _readings(tokens)[0] == "ナニ"


@pytest.mark.parametrize("following", ["ダ", "デ", "ト", "ノ", "テ", "ナノ", "ドウ"])  # noqa: RUF001
def test_nan_before_t_d_or_n(following: str) -> None:
    tokens = [Token("何", "ナン"), Token("x", following)]
    assert _readings(tokens)[0] == "ナン"


def test_nani_at_the_end() -> None:
    assert _readings([Token("それ", "ソレ"), Token("何", "ナン")]) == ["ソレ", "ナニ"]


def test_leaves_compounds_alone() -> None:
    assert _readings([Token("何度", "ナンド"), Token("も", "モ")]) == ["ナンド", "モ"]


def test_leaves_other_tokens_alone() -> None:
    assert _readings([Token("君", "キミ"), Token("を", "ヲ")]) == ["キミ", "ヲ"]
