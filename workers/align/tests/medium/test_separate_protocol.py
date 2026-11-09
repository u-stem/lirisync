"""Medium tests: what a `separate` request puts on the wire, checked against the schema.

The handler runs behind the real server and channel with a fake decoder,
encoder and model, so every line it writes can be validated without ffmpeg or
a model file.
"""

import io
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest

from lirisync_worker.protocol import PREFIX, ProtocolChannel
from lirisync_worker.separate import make_separate
from lirisync_worker.separation.stft import CHUNK
from lirisync_worker.server import Registry, Server
from tests.medium.support import is_valid, request

Audio = npt.NDArray[np.float32]


def _decode(_path: Path) -> Audio:
    return np.zeros((2, 2 * CHUNK), dtype=np.float32)


def _encode(_audio: Audio, path: Path) -> None:
    path.write_bytes(b"wav")


def _identity_model(_path: Path) -> Callable[[Audio], Audio]:
    return lambda chunk: chunk


@pytest.fixture(scope="module")
def messages(tmp_path_factory: pytest.TempPathFactory) -> list[dict[str, object]]:
    directory = tmp_path_factory.mktemp("separate-protocol")
    model = directory / "sep.onnx"
    model.write_bytes(b"x")
    params = {
        "input": str(directory / "song.mp3"),
        "output": str(directory / "vocals.wav"),
        "model": str(model),
    }
    handler = make_separate(decoder=_decode, encoder=_encode, model_loader=_identity_model)
    stream = io.StringIO()
    Server(Registry({"separate": handler})).serve(
        [request("separate", "p1", params)], ProtocolChannel(stream)
    )
    return [json.loads(line.removeprefix(PREFIX)) for line in stream.getvalue().splitlines()]


def test_every_line_is_a_schema_valid_response(messages: list[dict[str, object]]) -> None:
    assert all(is_valid("Response", m) for m in messages)


def test_progress_comes_first_and_the_result_last(messages: list[dict[str, object]]) -> None:
    kinds = [m["type"] for m in messages]

    assert kinds == ["progress"] * 7 + ["result"]


def test_the_final_result_is_a_schema_valid_separate_result(
    messages: list[dict[str, object]],
) -> None:
    assert is_valid("SeparateResult", messages[-1]["result"])


def test_every_message_carries_the_request_id(messages: list[dict[str, object]]) -> None:
    assert {m["id"] for m in messages} == {"p1"}
