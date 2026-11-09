"""Helpers shared by the medium tests that run or check the worker."""

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import jsonschema

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


def run_worker(
    stdin: str,
    *,
    noise: bool = False,
    timeout: float = 60,
    env: Mapping[str, str] | None = None,
) -> WorkerRun:
    """Run the worker process on `stdin`; `env` adds to (or overrides) the inherited environment."""
    full_env = {k: v for k, v in os.environ.items() if k != NOISE_ENV}
    full_env.update(env or {})
    if noise:
        full_env[NOISE_ENV] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "lirisync_worker"],
        input=stdin.encode("utf-8"),
        capture_output=True,
        env=full_env,
        timeout=timeout,
        check=False,
    )
    return WorkerRun(
        returncode=completed.returncode,
        stdout_lines=completed.stdout.decode("utf-8").splitlines(),
        stderr=completed.stderr.decode("utf-8"),
    )


def request(method: str, id_: str, params: Mapping[str, object] | None = None) -> str:
    return json.dumps({"v": 1, "id": id_, "method": method, "params": dict(params or {})}) + "\n"


def validator(definition: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    wrapper = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    jsonschema.Draft202012Validator.check_schema(wrapper)
    return jsonschema.Draft202012Validator(wrapper)


def is_valid(definition: str, instance: object) -> bool:
    return validator(definition).is_valid(instance)


def result_of(message: Mapping[str, object]) -> dict[str, object]:
    result = message["result"]
    if not isinstance(result, dict):
        raise TypeError("result is not an object")
    return result
