import hashlib
from contextlib import AbstractContextManager, nullcontext
from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path

import pytest

import fetch_separator_model as fetch

PAYLOAD = b"separator-model-bytes" * 1000
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class FakeResponse:
    """A response body that can announce a length and fail after some bytes."""

    def __init__(
        self, payload: bytes, content_length: str | None, fail_after: int | None = None
    ) -> None:
        self._body = BytesIO(payload)
        self._fail_after = fail_after
        self._served = 0
        self.headers: dict[str, str] = (
            {} if content_length is None else {"Content-Length": content_length}
        )

    def read(self, size: int, /) -> bytes:
        if self._fail_after is not None and self._served >= self._fail_after:
            raise IncompleteRead(b"", 1)
        block = self._body.read(min(size, 1000))
        self._served += len(block)
        return block


class Recorder:
    """An opener serving `payload` for any URL and remembering the URLs asked for."""

    def __init__(
        self,
        payload: bytes = PAYLOAD,
        content_length: str | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.payload = payload
        self.content_length = content_length
        self.fail_after = fail_after
        self.urls: list[str] = []

    def __call__(self, url: str) -> AbstractContextManager[fetch.Response]:
        self.urls.append(url)
        response = FakeResponse(self.payload, self.content_length, self.fail_after)
        return nullcontext(response)


def _fetch(target: Path, opener: Recorder, sha256: str = DIGEST) -> bool:
    return fetch.fetch_file(
        "https://example.invalid/m.onnx", target, sha256, opener, lambda _: None
    )


def test_a_missing_file_is_downloaded_with_the_pinned_content(tmp_path: Path) -> None:
    target = tmp_path / "m.onnx"

    _fetch(target, Recorder())

    assert target.read_bytes() == PAYLOAD


def test_a_download_reports_that_it_downloaded(tmp_path: Path) -> None:
    assert _fetch(tmp_path / "m.onnx", Recorder()) is True


def test_a_file_with_the_right_hash_is_not_downloaded_again(tmp_path: Path) -> None:
    target = tmp_path / "m.onnx"
    target.write_bytes(PAYLOAD)
    opener = Recorder()

    _fetch(target, opener)

    assert opener.urls == []


def test_skipping_reports_that_nothing_was_downloaded(tmp_path: Path) -> None:
    target = tmp_path / "m.onnx"
    target.write_bytes(PAYLOAD)

    assert _fetch(target, Recorder()) is False


def test_a_file_with_the_wrong_hash_is_replaced(tmp_path: Path) -> None:
    target = tmp_path / "m.onnx"
    target.write_bytes(b"truncated")

    _fetch(target, Recorder())

    assert target.read_bytes() == PAYLOAD


def test_a_download_with_the_wrong_hash_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _fetch(tmp_path / "m.onnx", Recorder(b"tampered"))


def test_a_rejected_download_leaves_no_file_behind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _fetch(tmp_path / "m.onnx", Recorder(b"tampered"))

    assert list(tmp_path.iterdir()) == []


def test_a_rejected_download_keeps_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "m.onnx"
    target.write_bytes(b"old")

    with pytest.raises(ValueError, match="SHA-256"):
        _fetch(target, Recorder(b"tampered"))

    assert target.read_bytes() == b"old"


def test_no_temporary_file_remains_after_a_download(tmp_path: Path) -> None:
    _fetch(tmp_path / "m.onnx", Recorder())

    assert [p.name for p in tmp_path.iterdir()] == ["m.onnx"]


def test_progress_is_logged(tmp_path: Path) -> None:
    lines: list[str] = []

    fetch.fetch_file(
        "https://example.invalid/m.onnx", tmp_path / "m.onnx", DIGEST, Recorder(), lines.append
    )

    assert any("m.onnx" in line for line in lines)


def test_the_url_names_the_pinned_revision() -> None:
    assert fetch.url_for("sep-all-int8.onnx") == (
        "https://huggingface.co/redbaty/ytm-vocal-separator/resolve/"
        "d9d3f27d58c4f9c0286a07ed541b18ceaa91f107/sep-all-int8.onnx"
    )


def test_default_files_leave_out_the_fp16_model() -> None:
    assert "sep-all-fp16.onnx" not in fetch.select_files(None, with_fp16=False)


def test_the_fp16_flag_adds_the_fp16_model_and_its_reference() -> None:
    names = fetch.select_files(None, with_fp16=True)

    assert {"sep-all-fp16.onnx", "ref-stems-all-fp16.f32"} <= set(names)


def test_default_files_include_the_int8_model_and_its_reference() -> None:
    names = fetch.select_files(None, with_fp16=False)

    assert {"sep-all-int8.onnx", "ref-input.f32", "ref-stems-all-int8.f32"} <= set(names)


def test_an_unknown_file_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        fetch.select_files(["other.bin"], with_fp16=False)


def test_every_pinned_hash_is_a_sha256_hex_digest() -> None:
    assert all(len(h) == 64 and int(h, 16) >= 0 for h in fetch.PINNED_SHA256.values())


def test_a_body_shorter_than_content_length_is_reported_as_truncated(tmp_path: Path) -> None:
    opener = Recorder(PAYLOAD, content_length=str(len(PAYLOAD) + 10))

    with pytest.raises(ValueError, match="truncated download"):
        _fetch(tmp_path / "m.onnx", opener)


def test_a_truncated_download_is_not_called_a_hash_mismatch(tmp_path: Path) -> None:
    opener = Recorder(PAYLOAD, content_length=str(len(PAYLOAD) + 10))

    with pytest.raises(ValueError, match="truncated") as caught:
        _fetch(tmp_path / "m.onnx", opener)

    assert "SHA-256" not in str(caught.value)


def test_a_truncated_download_leaves_no_file_behind(tmp_path: Path) -> None:
    opener = Recorder(PAYLOAD, content_length=str(len(PAYLOAD) + 10))

    with pytest.raises(ValueError, match="truncated"):
        _fetch(tmp_path / "m.onnx", opener)

    assert list(tmp_path.iterdir()) == []


def test_a_matching_content_length_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "m.onnx"

    _fetch(target, Recorder(PAYLOAD, content_length=str(len(PAYLOAD))))

    assert target.read_bytes() == PAYLOAD


def test_a_failure_in_the_middle_of_the_stream_leaves_no_file_behind(tmp_path: Path) -> None:
    with pytest.raises(IncompleteRead):
        _fetch(tmp_path / "m.onnx", Recorder(fail_after=2000))

    assert list(tmp_path.iterdir()) == []


def test_main_reports_an_unknown_file_name_as_a_failure(tmp_path: Path) -> None:
    assert fetch.main(["--dest", str(tmp_path), "--files", "other.bin"], Recorder()) == 1


def test_main_creates_the_destination_directory(tmp_path: Path) -> None:
    dest = tmp_path / "models" / "separator"

    fetch.main(["--dest", str(dest), "--files", "ref-input.f32"], Recorder())

    assert dest.is_dir()


def test_main_reports_a_broken_stream_as_a_failure(tmp_path: Path) -> None:
    opener = Recorder(fail_after=2000)

    assert fetch.main(["--dest", str(tmp_path), "--files", "ref-input.f32"], opener) == 1


def test_main_reports_a_hash_mismatch_as_a_failure(tmp_path: Path) -> None:
    assert fetch.main(["--dest", str(tmp_path), "--files", "ref-input.f32"], Recorder()) == 1
