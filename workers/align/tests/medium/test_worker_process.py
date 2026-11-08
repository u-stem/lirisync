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


def _run_worker(stdin: str, *, noise: bool = False) -> WorkerRun:
    env = {k: v for k, v in os.environ.items() if k != NOISE_ENV}
    if noise:
        env[NOISE_ENV] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "lirisync_worker"],
        input=stdin.encode("utf-8"),
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


def _request(method: str, id_: str) -> str:
    return json.dumps({"v": 1, "id": id_, "method": method, "params": {}}) + "\n"


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
