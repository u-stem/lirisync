import os
from pathlib import Path

import pytest

from lirisync_worker.protocol import ProtocolError
from lirisync_worker.request_files import (
    LatestModel,
    check_input_file,
    model_file_state,
    resolve_path,
)


class CountingLoader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, path: Path) -> str:
        self.calls += 1
        return f"model {self.calls}"


def _describe(path: Path) -> str:
    return f"model file {path}"


class RaisingLoader:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    def __call__(self, path: Path) -> str:
        raise self._error


# resolve_path


def test_resolve_path_makes_a_relative_path_absolute() -> None:
    assert resolve_path("a.wav", "input").is_absolute()


def test_resolve_path_refuses_a_path_with_a_nul_character() -> None:
    with pytest.raises(ProtocolError, match="input is not a usable path"):
        resolve_path("a\0b", "input")


# check_input_file


def test_check_input_file_accepts_a_missing_path(tmp_path: Path) -> None:
    check_input_file(tmp_path / "missing.wav", "audio")


def test_check_input_file_refuses_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ProtocolError, match="audio is not a regular file"):
        check_input_file(tmp_path, "audio")


# model_file_state


def test_model_file_state_reports_a_missing_file_as_model_missing(tmp_path: Path) -> None:
    with pytest.raises(ProtocolError) as caught:
        model_file_state(tmp_path / "missing.onnx")

    assert caught.value.code == "model_missing"


def test_model_file_state_reports_a_directory_as_model_missing(tmp_path: Path) -> None:
    with pytest.raises(ProtocolError) as caught:
        model_file_state(tmp_path)

    assert caught.value.code == "model_missing"


def test_model_file_state_changes_with_the_size(tmp_path: Path) -> None:
    path = tmp_path / "m.onnx"
    path.write_bytes(b"a")
    before = model_file_state(path)
    path.write_bytes(b"ab")
    os.utime(path, ns=(before[0], before[0]))

    assert model_file_state(path) != before


# LatestModel


def test_the_same_path_and_state_reuse_the_loaded_model(tmp_path: Path) -> None:
    loader = CountingLoader()
    models = LatestModel(loader, _describe)
    models.get(tmp_path, (1, 1))
    models.get(tmp_path, (1, 1))

    assert loader.calls == 1


def test_a_changed_state_loads_the_model_again(tmp_path: Path) -> None:
    loader = CountingLoader()
    models = LatestModel(loader, _describe)
    models.get(tmp_path, (1, 1))

    assert models.get(tmp_path, (2, 1)) == "model 2"


def test_only_the_latest_model_is_kept(tmp_path: Path) -> None:
    loader = CountingLoader()
    models = LatestModel(loader, _describe)
    models.get(tmp_path / "a", (1, 1))
    models.get(tmp_path / "b", (1, 1))
    models.get(tmp_path / "a", (1, 1))

    assert loader.calls == 3


def test_a_missing_runtime_is_an_internal_error(tmp_path: Path) -> None:
    models = LatestModel(RaisingLoader(ImportError("no onnxruntime")), _describe)

    with pytest.raises(ProtocolError) as caught:
        models.get(tmp_path, (1, 1))

    assert caught.value.code == "internal"


def test_running_out_of_memory_is_an_internal_error(tmp_path: Path) -> None:
    models = LatestModel(RaisingLoader(MemoryError()), _describe)

    with pytest.raises(ProtocolError) as caught:
        models.get(tmp_path, (1, 1))

    assert caught.value.code == "internal"


def test_a_model_that_fails_to_load_is_model_missing(tmp_path: Path) -> None:
    models = LatestModel(RaisingLoader(ValueError("bad graph")), _describe)

    with pytest.raises(ProtocolError, match=r"cannot use model file .*: bad graph"):
        models.get(tmp_path, (1, 1))


class FailingOnceLoader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, path: Path) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ValueError("bad")
        return "model"


def test_a_failed_load_is_not_kept(tmp_path: Path) -> None:
    models = LatestModel(FailingOnceLoader(), _describe)
    with pytest.raises(ProtocolError):
        models.get(tmp_path, (1, 1))

    assert models.get(tmp_path, (1, 1)) == "model"
