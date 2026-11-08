from collections.abc import Iterable, Mapping

import pytest

from lirisync_worker.anchor import make_anchor
from lirisync_worker.match_text import Reader, Token
from lirisync_worker.protocol import ProtocolError
from lirisync_worker.server import Registry, Session


def read_by_character(text: str) -> Iterable[Token]:
    return [Token(surface=ch, reading=ch) for ch in text]


def _words(text: str, start: int, step: int = 100) -> list[dict[str, object]]:
    return [
        {"startMs": start + k * step, "endMs": start + k * step + step - 20, "text": ch}
        for k, ch in enumerate(text)
    ]


def _params(
    lyrics: list[str], words: list[dict[str, object]], ignored: list[str] | None = None
) -> dict[str, object]:
    return {"lyrics": lyrics, "words": words, "ignored": ignored or []}


def _call(params: Mapping[str, object], reader: Reader = read_by_character) -> dict[str, object]:
    return make_anchor(lambda: reader)(Session(registry=Registry()), params)


def _code(params: Mapping[str, object]) -> str:
    with pytest.raises(ProtocolError) as error:
        _call(params)
    return error.value.code


def test_an_anchored_line_reports_its_times_and_ratio() -> None:
    result = _call(_params(["かぜがふく"], _words("かぜがふく", 1000)))
    assert result["lines"] == [
        {"status": "anchor", "startMs": 1000, "endMs": 1480, "matchRatio": 1.0, "ambiguous": False}
    ]


def test_a_line_that_is_not_sung_has_no_times() -> None:
    result = _call(_params([""], []))
    assert result["lines"] == [
        {
            "status": "not_sung",
            "startMs": None,
            "endMs": None,
            "matchRatio": 0.0,
            "ambiguous": False,
        }
    ]


def test_ignored_characters_do_not_count_against_the_match() -> None:
    result = _call(_params(["かぜx"], _words("かぜ", 0), ignored=["x"]))
    assert result["lines"] == [
        {"status": "anchor", "startMs": 0, "endMs": 180, "matchRatio": 1.0, "ambiguous": False}
    ]


def test_a_word_ending_before_it_starts_is_an_invalid_request() -> None:
    words = [{"startMs": 500, "endMs": 400, "text": "か"}]
    assert _code(_params(["か"], words)) == "invalid_request"


def test_words_out_of_time_order_are_an_invalid_request() -> None:
    words = _words("か", 1000) + _words("ぜ", 0)
    assert _code(_params(["かぜ"], words)) == "invalid_request"


def test_a_float_time_is_an_invalid_request() -> None:
    words = [{"startMs": 1.5, "endMs": 2, "text": "か"}]
    assert _code(_params(["か"], words)) == "invalid_request"


def test_an_unknown_param_is_an_invalid_request() -> None:
    assert _code({**_params([], []), "extra": 1}) == "invalid_request"


def test_an_ignored_entry_of_two_characters_is_an_invalid_request() -> None:
    assert _code(_params([], [], ignored=["xy"])) == "invalid_request"


def test_an_alignment_too_large_is_an_invalid_request() -> None:
    text = "か" * 8000
    assert _code(_params([text], _words(text, 0, step=10))) == "invalid_request"


def test_an_invalid_request_does_not_echo_the_lyrics() -> None:
    with pytest.raises(ProtocolError) as error:
        _call({"lyrics": ["ひみつのかし"], "words": "not a list", "ignored": []})
    assert "ひみつのかし" not in error.value.message


def test_the_reader_is_created_once_across_calls() -> None:
    created: list[Reader] = []

    def factory() -> Reader:
        created.append(read_by_character)
        return read_by_character

    handler = make_anchor(factory)
    session = Session(registry=Registry())
    for _ in range(2):
        handler(session, _params(["か"], _words("か", 0)))
    assert len(created) == 1


def test_a_repeated_ignored_character_is_an_invalid_request() -> None:
    assert _code(_params([], [], ignored=["x", "x"])) == "invalid_request"
