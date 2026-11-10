"""Medium tests: what a `refine` request puts on the wire, checked against the schema.

The handler runs behind the real server and channel with a fake decoder and
model, so every line it writes is validated without ffmpeg or a model file.
"""

import io
import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.ctc_model import SAMPLE_RATE, frame_count
from lirisync_worker.ctc_tokens import CharVocab
from lirisync_worker.match_text import Token
from lirisync_worker.protocol import PREFIX, ProtocolChannel
from lirisync_worker.refine import make_refine
from lirisync_worker.server import Registry, Server
from tests.medium.support import is_valid, request

Audio = npt.NDArray[np.float32]
LogProbs = npt.NDArray[np.float32]

SECONDS = 5


class _UniformModel:
    vocab = CharVocab({"<pad>": 0, "か": 1, "ぜ": 2})

    def log_probs(self, audio: Audio) -> LogProbs:
        return np.full((frame_count(audio.shape[0]), 3), np.log(1 / 3), dtype=np.float32)


def _decode(_path: Path) -> Audio:
    return np.zeros(SECONDS * SAMPLE_RATE, dtype=np.float32)


def _load(_path: Path) -> _UniformModel:
    return _UniformModel()


def _read(text: str) -> Iterable[Token]:
    return [Token(surface=ch, reading=ch) for ch in text]


@pytest.fixture(scope="module")
def messages(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, object]]:
    directory = tmp_path_factory.mktemp("refine-protocol")
    (directory / "model.int8.onnx").write_bytes(b"x")
    (directory / "vocab.json").write_text("{}")
    params = {
        "audio": str(directory / "vocals.wav"),
        "model": str(directory),
        "lyrics": ["かぜ", "かぜ", "かぜ", ""],
        "windows": [
            {"startMs": 1000, "endMs": 2000},
            None,
            {"startMs": 90_000, "endMs": 91_000},
            None,
        ],
        "spelling": "kana",
        "ignored": [],
        "marginMs": 200,
    }
    handler = make_refine(lambda: _read, decoder=_decode, model_loader=_load)
    stream = io.StringIO()
    Server(Registry({"refine": handler})).serve(
        [request("refine", "r1", params)], ProtocolChannel(stream)
    )
    return [json.loads(line.removeprefix(PREFIX)) for line in stream.getvalue().splitlines()]


def test_every_line_is_a_schema_valid_response(messages: list[dict[str, object]]) -> None:
    assert all(is_valid("Response", m) for m in messages)


def test_progress_comes_first_and_the_result_last(messages: list[dict[str, object]]) -> None:
    kinds = [m["type"] for m in messages]

    assert kinds == ["progress"] * 5 + ["result"]


def test_progress_is_in_the_refine_stage(messages: list[dict[str, object]]) -> None:
    assert {m["stage"] for m in messages if m["type"] == "progress"} == {"refine"}


def test_the_final_result_is_a_schema_valid_refine_result(
    messages: list[dict[str, object]],
) -> None:
    assert is_valid("RefineResult", messages[-1]["result"])


def test_the_statuses_cover_a_refined_an_unplaced_and_a_too_short_line(
    messages: list[dict[str, object]],
) -> None:
    result = messages[-1]["result"]
    assert isinstance(result, dict)

    assert [line["status"] for line in result["lines"]] == [
        "refined",
        "no_window",
        "too_short",
        "no_window",
    ]


def test_every_message_carries_the_request_id(messages: list[dict[str, object]]) -> None:
    assert {m["id"] for m in messages} == {"r1"}
