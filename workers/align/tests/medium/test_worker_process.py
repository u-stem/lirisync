"""Medium tests: run the real worker as a subprocess and check the wire behaviour."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import pytest

from lirisync_worker import __version__
from lirisync_worker.protocol import PREFIX

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "protocol" / "worker.schema.json"
NOISE_ENV = "LIRISYNC_WORKER_TEST_NOISE"


@dataclass(frozen=True)
class WorkerRun:
    returncode: int
    stdout_lines: list[str]
    stderr: str

    @property
    def messages(self) -> list[dict[str, object]]:
        return [json.loads(line.removeprefix(PREFIX)) for line in self.stdout_lines]


def _run_worker(stdin: str, *, noise: bool = False, timeout: float = 60) -> WorkerRun:
    env = {k: v for k, v in os.environ.items() if k != NOISE_ENV}
    if noise:
        env[NOISE_ENV] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "lirisync_worker"],
        input=stdin.encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    return WorkerRun(
        returncode=completed.returncode,
        stdout_lines=completed.stdout.decode("utf-8").splitlines(),
        stderr=completed.stderr.decode("utf-8"),
    )


def _request(method: str, id_: str, params: Mapping[str, object] | None = None) -> str:
    return json.dumps({"v": 1, "id": id_, "method": method, "params": dict(params or {})}) + "\n"


def _validator(definition: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    wrapper = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    jsonschema.Draft202012Validator.check_schema(wrapper)
    return jsonschema.Draft202012Validator(wrapper)


def _is_valid(definition: str, instance: object) -> bool:
    return _validator(definition).is_valid(instance)


def _result_of(message: Mapping[str, object]) -> dict[str, object]:
    result = message["result"]
    if not isinstance(result, dict):
        raise TypeError("result is not an object")
    return result


@pytest.fixture(scope="module")
def noisy_session() -> WorkerRun:
    return _run_worker(_request("hello", "h1") + _request("shutdown", "s1"), noise=True)


@pytest.fixture(scope="module")
def bad_input_session() -> WorkerRun:
    return _run_worker('{"v":1,\n[]\n{"v":2,"id":"x","method":"hello","params":{}}\n')


def test_clean_exit_after_shutdown(noisy_session: WorkerRun) -> None:
    assert noisy_session.returncode == 0


def test_hello_and_shutdown_each_produce_one_message(noisy_session: WorkerRun) -> None:
    assert [m["id"] for m in noisy_session.messages] == ["h1", "s1"]


def test_every_stdout_line_carries_the_prefix(noisy_session: WorkerRun) -> None:
    assert all(line.startswith(PREFIX) for line in noisy_session.stdout_lines)


def test_print_noise_does_not_reach_stdout(noisy_session: WorkerRun) -> None:
    assert "noise-print" not in "\n".join(noisy_session.stdout_lines)


def test_fd1_write_noise_does_not_reach_stdout(noisy_session: WorkerRun) -> None:
    assert "noise-fd1" not in "\n".join(noisy_session.stdout_lines)


def test_print_noise_goes_to_stderr(noisy_session: WorkerRun) -> None:
    assert "noise-print" in noisy_session.stderr


def test_fd1_write_noise_goes_to_stderr(noisy_session: WorkerRun) -> None:
    assert "noise-fd1" in noisy_session.stderr


def test_child_process_noise_does_not_reach_stdout(noisy_session: WorkerRun) -> None:
    assert "noise-child" not in "\n".join(noisy_session.stdout_lines)


def test_child_process_noise_goes_to_stderr(noisy_session: WorkerRun) -> None:
    assert "noise-child" in noisy_session.stderr


def test_protocol_lines_do_not_leak_to_stderr(noisy_session: WorkerRun) -> None:
    assert PREFIX not in noisy_session.stderr


def test_every_message_validates_as_response(noisy_session: WorkerRun) -> None:
    assert all(_is_valid("Response", m) for m in noisy_session.messages)


def test_hello_result_validates_as_hello_result(noisy_session: WorkerRun) -> None:
    assert _is_valid("HelloResult", _result_of(noisy_session.messages[0]))


def test_hello_result_reports_package_version(noisy_session: WorkerRun) -> None:
    result = _result_of(noisy_session.messages[0])

    assert result["worker"] == __version__


def test_shutdown_result_validates_as_shutdown_result(noisy_session: WorkerRun) -> None:
    assert _is_valid("ShutdownResult", _result_of(noisy_session.messages[1]))


def test_requests_used_by_the_tests_validate_as_request() -> None:
    assert _is_valid("Request", json.loads(_request("hello", "h1")))


def test_bad_lines_do_not_stop_the_worker(bad_input_session: WorkerRun) -> None:
    assert len(bad_input_session.messages) == 3


def test_bad_lines_produce_schema_valid_errors(bad_input_session: WorkerRun) -> None:
    assert all(_is_valid("Response", m) for m in bad_input_session.messages)


def test_bad_lines_report_expected_codes(bad_input_session: WorkerRun) -> None:
    codes = [m["code"] for m in bad_input_session.messages]

    assert codes == ["invalid_request", "invalid_request", "unsupported_version"]


def test_eof_without_shutdown_exits_zero(bad_input_session: WorkerRun) -> None:
    assert bad_input_session.returncode == 0


def test_noise_hook_is_off_by_default() -> None:
    run = _run_worker(_request("shutdown", "s1"))

    assert "noise-print" not in run.stderr


ANCHOR_PARAMS: dict[str, object] = {
    "lyrics": ["風が吹く", "", "空を飛ぶ"],
    "words": [
        {"startMs": 1000, "endMs": 1800, "text": "風が"},
        {"startMs": 1800, "endMs": 2500, "text": "吹く"},
        {"startMs": 4000, "endMs": 5200, "text": "空を飛ぶ"},
    ],
    "ignored": [],
}


@pytest.fixture(scope="module")
def anchor_session() -> WorkerRun:
    return _run_worker(_request("anchor", "a1", ANCHOR_PARAMS) + _request("shutdown", "s1"))


def test_anchor_params_used_by_the_tests_validate_as_anchor_params() -> None:
    assert _is_valid("AnchorParams", ANCHOR_PARAMS)


def test_anchor_result_validates_as_anchor_result(anchor_session: WorkerRun) -> None:
    assert _is_valid("AnchorResult", _result_of(anchor_session.messages[0]))


def _anchored_starts(result: Mapping[str, object]) -> list[object]:
    lines = result["lines"]
    if not isinstance(lines, list):
        raise TypeError("lines is not a list")
    return [line["startMs"] for line in lines if isinstance(line, dict)]


def test_anchor_places_lines_with_the_real_reader(anchor_session: WorkerRun) -> None:
    starts = _anchored_starts(_result_of(anchor_session.messages[0]))
    assert starts == [1000, None, 4000]


@pytest.fixture(scope="module")
def missing_model_session(tmp_path_factory: pytest.TempPathFactory) -> WorkerRun:
    directory = tmp_path_factory.mktemp("separate")
    params = {
        "input": str(directory / "song.mp3"),
        "output": str(directory / "vocals.wav"),
        "model": str(directory / "gone.onnx"),
    }
    return _run_worker(_request("separate", "p1", params) + _request("shutdown", "s1"))


def test_hello_lists_separate_in_registration_order(noisy_session: WorkerRun) -> None:
    methods = _result_of(noisy_session.messages[0])["methods"]

    assert methods == ["hello", "anchor", "separate", "shutdown"]


def test_separate_with_a_missing_model_is_a_schema_valid_error(
    missing_model_session: WorkerRun,
) -> None:
    assert _is_valid("Error", missing_model_session.messages[0])


def test_separate_with_a_missing_model_reports_model_missing(
    missing_model_session: WorkerRun,
) -> None:
    assert missing_model_session.messages[0]["code"] == "model_missing"


def test_separate_with_a_missing_model_does_not_stop_the_worker(
    missing_model_session: WorkerRun,
) -> None:
    assert missing_model_session.messages[1]["id"] == "s1"


FAKE_FFMPEG = """\
import os
import sys

# Behaves like a decoder that chokes on its input, after littering both streams.
os.write(1, b"fake-ffmpeg stdout junk, not a protocol line\\n")
sys.stdout.write("more stdout junk\\n")
sys.stderr.write("fake-ffmpeg: Invalid data found when processing input\\n")
sys.exit(1)
"""


def _fake_ffmpeg(directory: Path) -> Path:
    """An executable that runs `FAKE_FFMPEG`, on both POSIX and Windows."""
    script = directory / "fake_ffmpeg.py"
    script.write_text(FAKE_FFMPEG, encoding="utf-8")
    if sys.platform == "win32":
        launcher = directory / "fake-ffmpeg.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return launcher
    launcher = directory / "fake-ffmpeg"
    launcher.write_text(
        f"#!{sys.executable}\nexec(open({str(script)!r}).read())\n", encoding="utf-8"
    )
    launcher.chmod(0o755)
    return launcher


@pytest.fixture(scope="module")
def noisy_ffmpeg_session(tmp_path_factory: pytest.TempPathFactory) -> WorkerRun:
    directory = tmp_path_factory.mktemp("noisy-ffmpeg")
    model = directory / "sep.onnx"
    model.write_bytes(b"not read: decoding fails first")
    params = {
        "input": str(directory / "song.mp3"),
        "output": str(directory / "vocals.wav"),
        "model": str(model),
    }
    env = os.environ.copy()
    env["LIRISYNC_FFMPEG"] = str(_fake_ffmpeg(directory))
    completed = subprocess.run(
        [sys.executable, "-m", "lirisync_worker"],
        input=(_request("separate", "p1", params) + _request("shutdown", "s1")).encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    return WorkerRun(
        returncode=completed.returncode,
        stdout_lines=completed.stdout.decode("utf-8").splitlines(),
        stderr=completed.stderr.decode("utf-8"),
    )


def test_a_noisy_ffmpeg_does_not_break_the_protocol_framing(
    noisy_ffmpeg_session: WorkerRun,
) -> None:
    assert all(line.startswith(PREFIX) for line in noisy_ffmpeg_session.stdout_lines)


def test_a_noisy_ffmpegs_junk_does_not_reach_stdout(noisy_ffmpeg_session: WorkerRun) -> None:
    assert "junk" not in "\n".join(noisy_ffmpeg_session.stdout_lines)


def test_a_failing_ffmpeg_is_reported_as_audio_unreadable(
    noisy_ffmpeg_session: WorkerRun,
) -> None:
    assert noisy_ffmpeg_session.messages[0]["code"] == "audio_unreadable"


def test_the_error_for_a_failing_ffmpeg_carries_its_stderr(
    noisy_ffmpeg_session: WorkerRun,
) -> None:
    assert "Invalid data found" in str(noisy_ffmpeg_session.messages[0]["message"])


def test_the_error_for_a_failing_ffmpeg_is_schema_valid(noisy_ffmpeg_session: WorkerRun) -> None:
    assert _is_valid("Error", noisy_ffmpeg_session.messages[0])


def test_the_worker_survives_a_failing_ffmpeg(noisy_ffmpeg_session: WorkerRun) -> None:
    assert noisy_ffmpeg_session.messages[1]["id"] == "s1"
