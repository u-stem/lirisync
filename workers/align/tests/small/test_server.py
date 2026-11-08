"""Unit tests for dispatch and the serve loop, using in-memory streams."""

import io
import json
from collections.abc import Mapping

from lirisync_worker import __version__
from lirisync_worker.protocol import PREFIX, ProtocolChannel, ProtocolError
from lirisync_worker.server import Registry, Server, Session, hello


def _request(method: str, params: Mapping[str, object] | None = None, id_: str = "r1") -> str:
    return json.dumps({"v": 1, "id": id_, "method": method, "params": dict(params or {})}) + "\n"


def _serve(lines: list[str], server: Server | None = None) -> tuple[int, list[dict[str, object]]]:
    stream = io.StringIO()
    code = (server or Server()).serve(lines, ProtocolChannel(stream))
    messages = [
        json.loads(raw.removeprefix(PREFIX)) for raw in stream.getvalue().splitlines() if raw
    ]
    return code, messages


def _result_of(message: Mapping[str, object]) -> Mapping[str, object]:
    result = message["result"]
    if not isinstance(result, dict):
        raise TypeError("result is not an object")
    return result


def test_hello_returns_result_type() -> None:
    _, messages = _serve([_request("hello")])

    assert messages[0]["type"] == "result"


def test_hello_echoes_request_id() -> None:
    _, messages = _serve([_request("hello", id_="abc")])

    assert messages[0]["id"] == "abc"


def test_hello_reports_protocol_version() -> None:
    _, messages = _serve([_request("hello")])

    assert _result_of(messages[0])["protocol"] == 1


def test_hello_reports_worker_version() -> None:
    _, messages = _serve([_request("hello")])

    assert _result_of(messages[0])["worker"] == __version__


def test_hello_lists_supported_methods() -> None:
    _, messages = _serve([_request("hello")])

    assert _result_of(messages[0])["methods"] == ["hello", "shutdown"]


def test_hello_rejects_non_empty_params() -> None:
    _, messages = _serve([_request("hello", {"x": 1})])

    assert messages[0]["code"] == "invalid_request"


def test_unknown_method_is_reported() -> None:
    _, messages = _serve([_request("nope")])

    assert messages[0]["code"] == "unknown_method"


def test_unknown_method_keeps_request_id() -> None:
    _, messages = _serve([_request("nope", id_="r7")])

    assert messages[0]["id"] == "r7"


def test_unsupported_version_is_reported() -> None:
    _, messages = _serve(['{"v":2,"id":"r1","method":"hello","params":{}}\n'])

    assert messages[0]["code"] == "unsupported_version"


def test_bad_json_is_reported_with_null_id() -> None:
    _, messages = _serve(["{oops\n"])

    assert messages[0] == {
        "id": None,
        "type": "error",
        "code": "invalid_request",
        "message": messages[0]["message"],
    }


def test_loop_survives_bad_line() -> None:
    _, messages = _serve(["{oops\n", _request("hello")])

    assert [m["type"] for m in messages] == ["error", "result"]


def test_blank_lines_are_ignored() -> None:
    _, messages = _serve(["\n", "   \n", _request("hello")])

    assert len(messages) == 1


def test_shutdown_returns_empty_result() -> None:
    _, messages = _serve([_request("shutdown")])

    assert messages[0]["result"] == {}


def test_shutdown_exits_with_zero() -> None:
    code, _ = _serve([_request("shutdown")])

    assert code == 0


def test_shutdown_stops_processing_later_lines() -> None:
    _, messages = _serve([_request("shutdown"), _request("hello", id_="late")])

    assert len(messages) == 1


def test_shutdown_with_params_exits_with_zero() -> None:
    code, _ = _serve([_request("shutdown", {"x": 1})])

    assert code == 0


def test_loop_continues_after_shutdown_with_params() -> None:
    _, messages = _serve([_request("shutdown", {"x": 1}), _request("hello")])

    assert [m["type"] for m in messages] == ["error", "result"]


def test_eof_exits_with_zero() -> None:
    code, _ = _serve([])

    assert code == 0


def test_unexpected_handler_exception_becomes_internal_error() -> None:
    def boom(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    _, messages = _serve([_request("boom")], Server(Registry({"boom": boom})))

    assert messages[0]["code"] == "internal"


def test_loop_survives_unexpected_handler_exception() -> None:
    def boom(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    def ok(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
        return {}

    server = Server(Registry({"boom": boom, "ok": ok}))
    _, messages = _serve([_request("boom"), _request("ok")], server)

    assert [m["type"] for m in messages] == ["error", "result"]


def test_internal_error_does_not_leak_exception_text() -> None:
    def boom(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
        raise RuntimeError("secret-path")

    _, messages = _serve([_request("boom")], Server(Registry({"boom": boom})))

    assert "secret-path" not in json.dumps(messages)


def test_handler_protocol_error_keeps_its_code() -> None:
    def refuse(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
        raise ProtocolError("model_missing", "no model")

    _, messages = _serve([_request("refuse")], Server(Registry({"refuse": refuse})))

    assert messages[0]["code"] == "model_missing"


def test_registry_methods_are_listed_in_registration_order() -> None:
    def noop(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
        return {}

    registry = Registry({"b": noop, "a": noop})

    assert registry.methods() == ["b", "a"]


def _nan_result(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
    return {"x": float("nan")}


def _unserializable_result(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
    return {"x": object()}


def _ok(_session: Session, _params: Mapping[str, object]) -> dict[str, object]:
    return {}


def test_nan_result_becomes_internal_error() -> None:
    _, messages = _serve([_request("bad")], Server(Registry({"bad": _nan_result})))

    assert messages[0]["code"] == "internal"


def test_nan_result_error_keeps_request_id() -> None:
    _, messages = _serve([_request("bad", id_="r9")], Server(Registry({"bad": _nan_result})))

    assert messages[0]["id"] == "r9"


def test_loop_survives_nan_result() -> None:
    server = Server(Registry({"bad": _nan_result, "ok": _ok}))
    _, messages = _serve([_request("bad"), _request("ok")], server)

    assert [m["type"] for m in messages] == ["error", "result"]


def test_unserializable_result_becomes_internal_error() -> None:
    server = Server(Registry({"bad": _unserializable_result}))
    _, messages = _serve([_request("bad")], server)

    assert messages[0]["code"] == "internal"


def test_loop_survives_unserializable_result() -> None:
    server = Server(Registry({"bad": _unserializable_result, "ok": _ok}))
    _, messages = _serve([_request("bad"), _request("ok")], server)

    assert [m["type"] for m in messages] == ["error", "result"]


def test_hello_lists_methods_registered_after_server_construction() -> None:
    registry = Registry({"hello": hello})
    server = Server(registry)
    registry.register("late", _ok)

    _, messages = _serve([_request("hello")], server)

    assert _result_of(messages[0])["methods"] == ["hello", "late"]
