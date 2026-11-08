"""Unit tests for request parsing and message encoding."""

import io
import json
from pathlib import Path
from typing import get_args

import pytest

from lirisync_worker.protocol import (
    PREFIX,
    ErrorCode,
    ProtocolChannel,
    ProtocolError,
    encode_message,
    error_message,
    parse_request,
    result_message,
)

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "protocol" / "worker.schema.json"


def _line(**overrides: object) -> str:
    request: dict[str, object] = {"v": 1, "id": "r1", "method": "hello", "params": {}}
    request.update(overrides)
    return json.dumps(request)


def _error_of(line: str) -> ProtocolError:
    with pytest.raises(ProtocolError) as info:
        parse_request(line)
    return info.value


def test_parse_valid_request_keeps_method() -> None:
    request = parse_request(_line(method="hello"))

    assert request.method == "hello"


def test_parse_valid_request_keeps_id() -> None:
    request = parse_request(_line(id="abc"))

    assert request.id == "abc"


def test_parse_valid_request_keeps_params() -> None:
    request = parse_request(_line(params={"k": 1}))

    assert request.params == {"k": 1}


def test_parse_bad_json_is_invalid_request() -> None:
    error = _error_of("{not json")

    assert error.code == "invalid_request"


def test_parse_bad_json_has_no_id() -> None:
    error = _error_of("{not json")

    assert error.request_id is None


def test_parse_non_object_is_invalid_request() -> None:
    error = _error_of("[1, 2]")

    assert error.code == "invalid_request"


def test_parse_nan_literal_is_invalid_request() -> None:
    error = _error_of('{"v":1,"id":"r1","method":"hello","params":{"x":NaN}}')

    assert error.code == "invalid_request"


def test_parse_missing_params_is_invalid_request() -> None:
    error = _error_of('{"v":1,"id":"r1","method":"hello"}')

    assert error.code == "invalid_request"


def test_parse_schema_mismatch_keeps_known_id() -> None:
    error = _error_of('{"v":1,"id":"r1","method":"hello"}')

    assert error.request_id == "r1"


def test_parse_empty_id_is_invalid_request() -> None:
    error = _error_of(_line(id=""))

    assert error.code == "invalid_request"


def test_parse_non_string_id_is_invalid_request() -> None:
    error = _error_of(_line(id=7))

    assert error.request_id is None


def test_parse_empty_method_is_invalid_request() -> None:
    error = _error_of(_line(method=""))

    assert error.code == "invalid_request"


def test_parse_extra_field_is_invalid_request() -> None:
    error = _error_of(_line(extra=True))

    assert error.code == "invalid_request"


def test_parse_boolean_version_is_invalid_request() -> None:
    error = _error_of(_line(v=True))

    assert error.code == "invalid_request"


def test_parse_other_version_is_unsupported_version() -> None:
    error = _error_of(_line(v=2))

    assert error.code == "unsupported_version"


def test_parse_other_version_keeps_id() -> None:
    error = _error_of(_line(v=2, id="r9"))

    assert error.request_id == "r9"


def test_parse_other_version_wins_over_other_schema_problems() -> None:
    error = _error_of('{"v":2,"id":"r1","future":"shape"}')

    assert error.code == "unsupported_version"


def test_parse_other_version_without_valid_id_has_null_id() -> None:
    error = _error_of('{"v":2,"method":"hello","params":{}}')

    assert error.request_id is None


def test_encode_message_starts_with_prefix() -> None:
    line = encode_message(result_message("r1", {}))

    assert line.startswith(PREFIX)


def test_encode_message_ends_with_single_newline() -> None:
    line = encode_message(result_message("r1", {}))

    assert line.endswith("}\n")


def test_encode_message_is_one_line() -> None:
    line = encode_message(error_message("r1", "internal", "a\nb"))

    assert line.count("\n") == 1


def test_encode_message_is_compact() -> None:
    line = encode_message(result_message("r1", {"a": 1}))

    assert line == '@@lirisync {"id":"r1","type":"result","result":{"a":1}}\n'


def test_encode_message_keeps_non_ascii_readable() -> None:
    line = encode_message(error_message(None, "internal", "歌詞"))

    assert "歌詞" in line


def test_error_message_has_null_id_when_unknown() -> None:
    message = error_message(None, "invalid_request", "bad")

    assert message == {
        "id": None,
        "type": "error",
        "code": "invalid_request",
        "message": "bad",
    }


def test_channel_writes_each_message_as_prefixed_line() -> None:
    stream = io.StringIO()
    channel = ProtocolChannel(stream)

    channel.send(result_message("r1", {}))

    assert stream.getvalue() == '@@lirisync {"id":"r1","type":"result","result":{}}\n'


def test_channel_flushes_after_each_message() -> None:
    class CountingStream(io.StringIO):
        flushes = 0

        def flush(self) -> None:
            type(self).flushes += 1
            super().flush()

    stream = CountingStream()
    channel = ProtocolChannel(stream)

    channel.send(result_message("r1", {}))

    assert CountingStream.flushes == 1


def test_error_codes_match_the_schema_enum() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert set(get_args(ErrorCode)) == set(schema["$defs"]["ErrorCode"]["enum"])
